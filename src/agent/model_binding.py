# src/agent/model_binding.py
"""Bind tools and system messages for stable, cache-friendly model requests."""

from __future__ import annotations

from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import SystemMessage
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool

CACHE_BREAKPOINT = {"type": "ephemeral"}


def _unwrap_chat_model(model: BaseChatModel | Runnable) -> BaseChatModel:
    current = model
    while hasattr(current, "bound"):
        current = current.bound  # type: ignore[attr-defined]
    return current  # type: ignore[return-value]


def bound_tool_names(bound: Runnable) -> list[str]:
    """Tool names on a bind_tools() result, in API order."""
    kwargs = getattr(bound, "kwargs", None) or {}
    tools = kwargs.get("tools") or []
    return [t["name"] for t in tools]


def bind_agent_tools(model: BaseChatModel, tools: list[BaseTool]) -> Runnable:
    """Bind tools sorted by name; mark Anthropic tool definitions cacheable at the end."""
    ordered = sorted(tools, key=lambda t: t.name)
    bound = model.bind_tools(ordered)
    if not isinstance(_unwrap_chat_model(model), ChatAnthropic):
        return bound
    if not ordered:
        return bound
    kwargs = dict(bound.kwargs)
    formatted = list(kwargs.get("tools") or [])
    if not formatted:
        return bound
    last = dict(formatted[-1])
    last["cache_control"] = CACHE_BREAKPOINT
    formatted[-1] = last
    kwargs["tools"] = formatted
    return bound.bound.bind(**kwargs)


def anthropic_system_message(system_text: str) -> SystemMessage:
    """System prompt with an Anthropic cache breakpoint on the text block."""
    return SystemMessage(
        content=[
            {
                "type": "text",
                "text": system_text,
                "cache_control": CACHE_BREAKPOINT,
            }
        ]
    )


def system_message_for_model(system_text: str, model: BaseChatModel | Runnable) -> SystemMessage:
    if isinstance(_unwrap_chat_model(model), ChatAnthropic):
        return anthropic_system_message(system_text)
    return SystemMessage(content=system_text)
