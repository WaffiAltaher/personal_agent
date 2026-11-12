"""Build the token-bounded message view sent to the model (state stays intact)."""

from __future__ import annotations

import copy
import json

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool
from langchain_core.utils.function_calling import convert_to_openai_tool

from agent.config import settings

TRUNCATION_MARKER = "[Tool result truncated at {max_tokens} tokens]"
CLEARED_STUB = "[result cleared, ~{tokens} tokens; call the tool again if needed]"
CLEARED_STUB_PREFIX = CLEARED_STUB.split("{")[0]


def estimate_tokens(text: str) -> int:
    return len(text) // 4


def _text_blocks(content: list) -> bool:
    return bool(content) and all(
        isinstance(block, dict) and block.get("type") == "text" for block in content
    )


def cap_tool_result_content(content: str | list, max_tokens: int | None = None) -> str | list:
    if isinstance(content, list):
        if not _text_blocks(content):
            return content
        joined = "".join(str(block.get("text", "")) for block in content)
        return cap_tool_result_content(joined, max_tokens)
    cap = settings.tool_result_max_tokens if max_tokens is None else max_tokens
    text = content if isinstance(content, str) else str(content)
    if estimate_tokens(text) <= cap:
        return text
    max_chars = cap * 4
    marker = TRUNCATION_MARKER.format(max_tokens=cap)
    keep = max_chars - len(marker)
    if keep < 0:
        keep = 0
    return text[:keep] + marker


def _message_content_tokens(msg: BaseMessage) -> int:
    total = estimate_tokens(str(msg.content))
    if isinstance(msg, AIMessage) and msg.tool_calls:
        total += estimate_tokens(json.dumps(msg.tool_calls, default=str))
    return total


def estimate_tool_schema_tokens(tools: list[BaseTool]) -> int:
    if not tools:
        return 0
    schemas = [convert_to_openai_tool(t) for t in tools]
    return estimate_tokens(json.dumps(schemas, default=str))


def estimate_context_tokens(
    *,
    state_messages: list[BaseMessage],
    system_text: str,
    tools: list[BaseTool],
    last_model_input_tokens: int | None,
    message_count_at_last_model_call: int,
) -> int:
    if last_model_input_tokens is None:
        total = estimate_tokens(system_text) + estimate_tool_schema_tokens(tools)
        for msg in state_messages:
            total += _message_content_tokens(msg)
        return total

    delta = state_messages[message_count_at_last_model_call:]
    added = sum(_message_content_tokens(m) for m in delta)
    return last_model_input_tokens + added


def _view_token_total(system_text: str, tools: list[BaseTool], messages: list[BaseMessage]) -> int:
    total = estimate_tokens(system_text) + estimate_tool_schema_tokens(tools)
    for msg in messages:
        total += _message_content_tokens(msg)
    return total


def _latest_ai_tool_batch(messages: list[BaseMessage]) -> AIMessage | None:
    for message in reversed(messages):
        if isinstance(message, AIMessage) and getattr(message, "tool_calls", None):
            return message
    return None


def _protected_tool_call_ids(messages: list[BaseMessage]) -> set[str]:
    """Keep the latest tool batch full only until the model has had a turn after its results."""
    last_ai = _latest_ai_tool_batch(messages)
    if last_ai is None:
        return set()
    batch_ids = {tc["id"] for tc in last_ai.tool_calls or []}
    answered = {m.tool_call_id for m in messages if isinstance(m, ToolMessage)}
    unanswered = batch_ids - answered
    if unanswered:
        return unanswered

    last_batch_tool_idx = -1
    for i, msg in enumerate(messages):
        if isinstance(msg, ToolMessage) and msg.tool_call_id in batch_ids:
            last_batch_tool_idx = i
    if last_batch_tool_idx < 0:
        return set()
    for msg in messages[last_batch_tool_idx + 1 :]:
        if isinstance(msg, AIMessage):
            return set()
    return batch_ids


def _is_cleared_stub(message: ToolMessage) -> bool:
    content = message.content
    if isinstance(content, str):
        return CLEARED_STUB_PREFIX in content
    return False


def _cleared_stub(original: ToolMessage) -> ToolMessage:
    tokens = _message_content_tokens(original)
    return ToolMessage(
        content=CLEARED_STUB.format(tokens=tokens),
        tool_call_id=original.tool_call_id,
        name=getattr(original, "name", None),
        status=getattr(original, "status", None),
    )


def build_model_view(
    state_messages: list[BaseMessage],
    system_text: str,
    tools: list[BaseTool],
    last_model_input_tokens: int | None,
    message_count_at_last_model_call: int,
    *,
    system_message: SystemMessage | None = None,
    clear_threshold: int | None = None,
    clear_target: int | None = None,
    stubbed_tool_call_ids: set[str] | None = None,
) -> tuple[list[BaseMessage], set[str]]:
    threshold = settings.context_clear_threshold if clear_threshold is None else clear_threshold
    target = settings.context_clear_target if clear_target is None else clear_target
    stubbed = set(stubbed_tool_call_ids or ())

    context_tokens = estimate_context_tokens(
        state_messages=state_messages,
        system_text=system_text,
        tools=tools,
        last_model_input_tokens=last_model_input_tokens,
        message_count_at_last_model_call=message_count_at_last_model_call,
    )
    working = copy.deepcopy(state_messages)
    system_msg = system_message if system_message is not None else SystemMessage(content=system_text)
    protected = _protected_tool_call_ids(working)

    def view_total() -> int:
        return _view_token_total(system_text, tools, working)

    def apply_stub(idx: int, original: ToolMessage) -> None:
        nonlocal stubbed
        if original.tool_call_id in protected:
            return
        if not _is_cleared_stub(original):
            working[idx] = _cleared_stub(original)
            stubbed.add(original.tool_call_id)

    for idx, msg in enumerate(working):
        if isinstance(msg, ToolMessage) and msg.tool_call_id in stubbed:
            apply_stub(idx, msg)

    if context_tokens > threshold:
        # context_tokens is the provider's count; view_total() is the chars/4 estimate, which can be
        # far below it (JSON, non-English text). Scale the estimate so the target is in the same tokens.
        scale = context_tokens / max(view_total(), 1)
        tool_indices = [i for i, m in enumerate(working) if isinstance(m, ToolMessage)]
        for idx in tool_indices:
            if view_total() * scale <= target:
                break
            original = working[idx]
            if isinstance(original, ToolMessage):
                apply_stub(idx, original)

    view = [system_msg] + working
    if not view:
        raise RuntimeError("model view must not be empty")

    first_human = next((m for m in working if isinstance(m, HumanMessage)), None)
    if first_human is not None:
        assert view[1].content == first_human.content

    tool_ids = {
        tc["id"]
        for msg in working
        if isinstance(msg, AIMessage)
        for tc in (msg.tool_calls or [])
    }
    answered = {m.tool_call_id for m in working if isinstance(m, ToolMessage)}
    if tool_ids - answered:
        raise RuntimeError("model view has unanswered tool calls")

    return view, stubbed
