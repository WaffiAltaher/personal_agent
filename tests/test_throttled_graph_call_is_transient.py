import pytest
from mcp.types import CallToolResult, TextContent

from agent.tools.mcp_loader import TransientMcpError, _boundary_interceptor
from agent.tools.ms365_mcp import ms365_fixture_server


@pytest.mark.asyncio
async def test_a_throttled_graph_call_is_transient():
    # Graph throttles with 429; the real server reports it as a tool error with this wording.
    intercept = _boundary_interceptor(ms365_fixture_server())

    async def throttled(request):
        text = '{"error":"Microsoft Graph API error: 429 Too Many Requests - {\\"error\\":{\\"code\\":\\"TooManyRequests\\"}}"}'
        return CallToolResult(isError=True, content=[TextContent(type="text", text=text)])

    with pytest.raises(TransientMcpError):
        await intercept(None, throttled)
