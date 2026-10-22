"""Ticket 26: the fallback's error message and the normalised tool schemas sent to models."""

import pytest
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import StructuredTool, tool
from langchain_google_genai import ChatGoogleGenerativeAI

import agent.graph as graph_module
from agent.graph import build_graph
from agent.model_binding import bind_agent_tools
from agent.tools.classification import read_tool


@pytest.mark.asyncio
async def test_fallback_message_has_error_status_and_names_the_actual_failure(scripted_model, monkeypatch):
    async def buggy_wrapper(request, execute):
        raise RuntimeError("bug in the retry wrapper: code 4711")

    monkeypatch.setattr(graph_module, "retry_tool_call", buggy_wrapper)

    @read_tool
    @tool("read_a")
    async def read_a() -> str:
        """Reads a."""
        return "a"

    calls = [{"id": "c1", "name": "read_a", "args": {}}]
    graph = build_graph(tools=[read_a], model=scripted_model(
        [AIMessage(content="", tool_calls=calls), AIMessage(content="It failed.")]))
    result = await graph.ainvoke({"messages": [HumanMessage(content="go")]})

    [fallback] = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert fallback.tool_call_id == "c1"
    assert fallback.status == "error"
    assert "bug in the retry wrapper: code 4711" in fallback.content
    assert "RuntimeError" in fallback.content
    assert "try again later" not in fallback.content
    assert "temporarily unavailable" not in fallback.content


def _contains_key(node, keys: frozenset[str]) -> bool:
    if isinstance(node, dict):
        return any(k in keys or _contains_key(v, keys) for k, v in node.items())
    if isinstance(node, list):
        return any(_contains_key(item, keys) for item in node)
    return False


def _mcp_style_tools() -> list[StructuredTool]:
    """Tools whose schemas carry the keys Gemini rejects, as MCP servers and Tavily send them."""
    async def _run(**kwargs) -> str:
        return "ok"

    download_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {
            "id": {"type": "string"},
            "options": {
                "type": "object",
                "properties": {"format": {"type": "string"}},
                "additionalProperties": False,
            },
        },
        "required": ["id"],
        "additionalProperties": False,
    }
    search_schema = {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "additionalProperties": True,
    }
    return [
        StructuredTool(name="ms365_download-bytes", description="Download.", args_schema=download_schema, coroutine=_run),
        StructuredTool(name="search_things", description="Search.", args_schema=search_schema, coroutine=_run),
    ]


def test_gemini_bound_tool_schemas_have_no_unsupported_keys():
    model = ChatGoogleGenerativeAI(model="gemini-3.8-flash", google_api_key="test-key")
    bound = bind_agent_tools(model, _mcp_style_tools())

    assert len(bound.kwargs["tools"]) == 2
    assert not _contains_key(bound.kwargs["tools"], frozenset({"$schema", "additionalProperties"}))
    # The properties that matter to the model survive the cleanup.
    download = bound.kwargs["tools"][0]["function"]["parameters"]
    assert download["required"] == ["id"]
    assert download["properties"]["options"]["properties"] == {"format": {"type": "string"}}


def test_anthropic_bound_tool_schemas_have_no_unsupported_keys_and_stay_cacheable():
    model = ChatAnthropic(model="claude-sonnet-5-5", api_key="sk-ant-test")
    bound = bind_agent_tools(model, _mcp_style_tools())

    assert not _contains_key(bound.kwargs["tools"], frozenset({"$schema", "additionalProperties"}))
    assert bound.kwargs["tools"][-1]["cache_control"] == {"type": "ephemeral"}


def test_property_named_like_a_dropped_key_is_kept():
    """Only schema keywords are dropped; a property that happens to be called additionalProperties stays."""
    from agent.model_binding import without_unsupported_schema_keys

    schema = {
        "type": "object",
        "properties": {"additionalProperties": {"type": "string"}},
        "additionalProperties": False,
    }
    cleaned = without_unsupported_schema_keys(schema)
    assert cleaned == {"type": "object", "properties": {"additionalProperties": {"type": "string"}}}
