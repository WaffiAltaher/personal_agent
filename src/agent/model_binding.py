# src/agent/model_binding.py
"""Bind tools and system messages for stable, cache-friendly model requests."""

from __future__ import annotations

from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import SystemMessage
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool
from langchain_core.utils.function_calling import convert_to_openai_tool

CACHE_BREAKPOINT = {"type": "ephemeral"}

# JSON Schema keys the Gemini converter does not support: it logs a warning per key on every
# request and ignores them. Dropped from every bound tool schema, at any depth. The Microsoft 365
# download tool's `additionalProperties: false` is dropped deliberately: Gemini cannot express it,
# so that tool is bound without it, like the others.
UNSUPPORTED_SCHEMA_KEYS = frozenset({"$schema", "additionalProperties"})


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


def without_unsupported_schema_keys(node):
    """Return a copy of a JSON Schema with UNSUPPORTED_SCHEMA_KEYS removed at every depth."""
    if isinstance(node, list):
        return [without_unsupported_schema_keys(item) for item in node]
    if not isinstance(node, dict):
        return node
    cleaned = {}
    for key, value in node.items():
        if key in UNSUPPORTED_SCHEMA_KEYS:
            continue
        if key == "properties" and isinstance(value, dict):
            # Property names are data, not schema keywords: only their sub-schemas are cleaned.
            cleaned[key] = {name: without_unsupported_schema_keys(sub) for name, sub in value.items()}
        else:
            cleaned[key] = without_unsupported_schema_keys(value)
    return cleaned


def _normalised_tool_spec(tool: BaseTool) -> dict:
    return without_unsupported_schema_keys(convert_to_openai_tool(tool))


def bind_agent_tools(model: BaseChatModel, tools: list[BaseTool]) -> Runnable:
    """Bind tools sorted by name, with normalised schemas; mark Anthropic definitions cacheable at the end."""
    ordered = sorted(tools, key=lambda t: t.name)
    bound = model.bind_tools([_normalised_tool_spec(t) for t in ordered])
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
