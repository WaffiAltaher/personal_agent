"""Build episodic run records from a completed graph result."""

from __future__ import annotations

from datetime import date

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

from agent.memory.episodic import RunRecord
from agent.pricing import cost_usd


def _final_output(messages: list[BaseMessage]) -> str:
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and not getattr(msg, "tool_calls", None):
            content = msg.content
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                return " ".join(
                    block["text"]
                    for block in content
                    if isinstance(block, dict) and block.get("type") == "text"
                )
    return ""


def _tools_called(messages: list[BaseMessage]) -> list[str]:
    return [
        tc["name"]
        for msg in messages
        if isinstance(msg, AIMessage)
        for tc in getattr(msg, "tool_calls", [])
    ]


def _sum_usage_metadata(messages: list[BaseMessage]) -> tuple[dict | None, dict | None]:
    """Return (episodic token_usage dict, LangChain usage dict for pricing)."""
    prompt = completion = total = 0
    priced: dict = {
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "input_token_details": {},
    }
    found = False
    for msg in messages:
        if not isinstance(msg, AIMessage):
            continue
        meta = getattr(msg, "usage_metadata", None)
        if not meta:
            continue
        found = True
        prompt += meta.get("input_tokens", 0)
        completion += meta.get("output_tokens", 0)
        total += meta.get("total_tokens", 0) or (
            meta.get("input_tokens", 0) + meta.get("output_tokens", 0)
        )
        priced["input_tokens"] += meta.get("input_tokens", 0)
        priced["output_tokens"] += meta.get("output_tokens", 0)
        priced["total_tokens"] += meta.get("total_tokens", 0) or (
            meta.get("input_tokens", 0) + meta.get("output_tokens", 0)
        )
        details = meta.get("input_token_details") or {}
        merged = priced["input_token_details"]
        for key, value in details.items():
            merged[key] = merged.get(key, 0) + (value or 0)

    if not found:
        return None, None
    episodic_usage = {"prompt": prompt, "completion": completion, "total": total}
    if not priced["input_token_details"]:
        priced.pop("input_token_details")
    return episodic_usage, priced


def _is_step_limit_answer(message: BaseMessage | None) -> bool:
    return (
        isinstance(message, AIMessage)
        and not getattr(message, "tool_calls", None)
        and isinstance(message.content, str)
        and "step limit" in message.content.lower()
    )


def _detect_outcome(messages: list[BaseMessage], *, error: str | None) -> str:
    if error:
        return "error"
    if messages and _is_step_limit_answer(messages[-1]):
        return "step limit"
    for msg in messages:
        if isinstance(msg, ToolMessage) and msg.status == "error":
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            if "rejected by the user" in content.lower():
                return "rejected"
    return "completed"


def build_run_record(
    result: dict,
    user_input: str,
    *,
    model_name: str,
    run_date: date,
    error: str | None = None,
) -> RunRecord:
    messages: list[BaseMessage] = result.get("messages", [])
    token_usage, priced_usage = _sum_usage_metadata(messages)
    run_cost = (
        cost_usd(model_name, priced_usage, on=run_date) if priced_usage is not None else None
    )
    return RunRecord(
        user_input=user_input,
        final_output=_final_output(messages),
        tools_called=_tools_called(messages),
        token_usage=token_usage,
        cost_usd=run_cost,
        outcome=_detect_outcome(messages, error=error),
        error_message=error,
    )
