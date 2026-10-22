"""MCP tool results as text blocks must be capped like string results."""

import pytest
from langchain_core.messages import ToolMessage

from agent.config import settings
from agent.memory.context_view import cap_tool_result_content, estimate_tokens


def test_list_of_text_blocks_over_cap_becomes_capped_string(monkeypatch):
    monkeypatch.setattr(settings, "tool_result_max_tokens", 50)
    huge = "y" * (60 * 4)
    blocks = [{"type": "text", "text": huge}]
    capped = cap_tool_result_content(blocks)
    assert isinstance(capped, str)
    assert estimate_tokens(capped) <= 50
    assert "truncated" in capped.lower()


def test_non_text_block_list_is_unchanged():
    content = [{"type": "image", "url": "http://example.com/x"}]
    assert cap_tool_result_content(content) == content


@pytest.mark.asyncio
async def test_retry_wrapper_caps_list_content(monkeypatch):
    from langchain_core.tools import tool

    from agent.graph import retry_tool_call
    from agent.tools.classification import read_tool

    monkeypatch.setattr(settings, "tool_result_max_tokens", 40)
    huge = "z" * (50 * 4)
    blocks = [{"type": "text", "text": huge}]

    @read_tool
    @tool("mcp_tool")
    async def mcp_tool() -> str:
        """MCP tool."""
        return "unused"

    async def execute(_request):
        return ToolMessage(content=blocks, tool_call_id="c1", name="mcp_tool")

    request = type("R", (), {"tool_call": {"id": "c1", "name": "mcp_tool"}, "tool": mcp_tool})()
    result = await retry_tool_call(request, execute)
    assert isinstance(result.content, str)
    assert "truncated" in result.content.lower()
