# src/agent/tools/ms365_mcp.py
"""The MS365 MCP server: the real one (@softeria/ms-365-mcp-server) or its Fixture world stand-in.

Both are loaded under the same name ("ms365"), with the same hidden tools and the same
classification, so the agent sees the same tools against either.
"""

import os
import sys

from agent.config import Settings, settings as default_settings
from agent.tools.mcp_loader import LoginCheck, McpServer

NAME = "ms365"

# Login and account management stay out of the model's reach.
HIDDEN_TOOLS = frozenset({
    "login",
    "logout",
    "remove-account",
    "select-account",
    "verify-login",
    "list-accounts",
})

PACKAGE = "@softeria/ms-365-mcp-server@0.119.0"

# A missing or expired login: checked at startup with verify-login, and recognised in
# tool errors by the real server's wording (a token error, or Graph answering 401).
LOGIN = LoginCheck(
    service="Microsoft 365",
    command=f"npx -y {PACKAGE} --login (with MS365_MCP_CLIENT_ID and MS365_MCP_TENANT_ID set)",
    check_tool="verify-login",
    error_patterns=(
        r"No valid token found",
        r"No access token available",
        r"token may have expired",
        r"Microsoft Graph API error: 401\b",
    ),
)

# The real server reports Graph errors as tool errors worded
# "Microsoft Graph API error: <status> <reason> - <body>"; 429 and 5xx are transient.
TRANSIENT_ERRORS = (r"Microsoft Graph API error: (429|5\d\d)\b",)


def ms365_server(settings: Settings = default_settings) -> McpServer:
    """The real server, through npx, against the ITtopia tenant."""
    if not (settings.ms365_mcp_client_id and settings.ms365_mcp_tenant_id):
        return McpServer(
            name=NAME,
            connection=None,
            unavailable_reason="MS365_MCP_CLIENT_ID and MS365_MCP_TENANT_ID are not set",
        )
    return McpServer(
        name=NAME,
        connection={
            "command": "npx",
            "args": [
                "-y",
                PACKAGE,
                "--preset",
                "outlook",
                "--read-only",
            ],
            "transport": "stdio",
            "env": {
                **os.environ,
                "MS365_MCP_CLIENT_ID": settings.ms365_mcp_client_id,
                "MS365_MCP_TENANT_ID": settings.ms365_mcp_tenant_id,
            },
        },
        hidden_tools=HIDDEN_TOOLS,
        login=LOGIN,
        transient_errors=TRANSIENT_ERRORS,
        # Fail-closed classification: the pinned server marks GET tools readOnlyHint,
        # so we trust that annotation; every other tool is a Write action.
        trust_read_only_hint=True,
    )


def ms365_fixture_server() -> McpServer:
    """The Fixture world's stand-in (fixture_world.ms365), over stdio like the real one."""
    return McpServer(
        name=NAME,
        connection={
            "command": sys.executable,
            "args": ["-m", "fixture_world.ms365"],
            "transport": "stdio",
            # Passes FIXTURE_WORLD_TODAY through when set (the stdio client's default env drops it).
            "env": {**os.environ},
        },
        hidden_tools=HIDDEN_TOOLS,
        login=LOGIN,
        transient_errors=TRANSIENT_ERRORS,
        trust_read_only_hint=True,
    )
