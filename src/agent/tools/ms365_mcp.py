from langchain_mcp_adapters.client import MultiServerMCPClient
from agent.config import settings
from agent.tools.classification import classify_mcp_tools
import os


async def load_ms365_tools():
    mcp_env = {
        **os.environ,
        "MS365_MCP_CLIENT_ID": settings.ms365_mcp_client_id,
        "MS365_MCP_TENANT_ID": settings.ms365_mcp_tenant_id,
    }

    client = MultiServerMCPClient(
        {
            "ms365": {
                "command": "npx",
                "args": [
                    "-y",
                    "@softeria/ms-365-mcp-server@0.119.0",
                    "--preset",
                    "outlook",
                    "--read-only",
                ],
                "transport": "stdio",
                "env": mcp_env,
            }
        },
        tool_name_prefix=True,
    )
    tools = await client.get_tools()
    # Fail-closed classification: the pinned server marks GET tools readOnlyHint,
    # so we trust that annotation; every other tool is a Write action.
    return classify_mcp_tools(
        [
            tool for tool in tools
            if tool.name not in {
                "ms365_login",
                "ms365_logout",
                "ms365_remove-account",
                "ms365_select-account",
                "ms365_verify-login",
            }
        ],
        trust_read_only_hint=True,
    )
