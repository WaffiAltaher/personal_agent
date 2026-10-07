# src/agent/tools/informer.py
"""The Informer MCP server (src/informer_mcp, ADR-006): against real Informer, or the Fixture world.

Both are loaded under the same name ("informer"), with the same classification, so the
agent sees the same tools against either.
"""

import os
import sys

from agent.config import Settings, settings as default_settings
from agent.tools.mcp_loader import McpServer

NAME = "informer"

# The server is ours and exposes no write endpoints (ADR-006), but tools are still listed
# by name rather than trusting readOnlyHint: a tool added to the server without being
# listed here is a gated Write action until someone checks it (ADR-010).
READ_TOOLS = frozenset({
    "list_relations",
    "get_relation",
    "list_sales_invoices",
    "get_sales_invoice",
    "list_overdue_invoices",
    "trial_balance",
})


def informer_server(settings: Settings = default_settings) -> McpServer:
    """The real server, over stdio, against Informer API v2 with ITtopia's API key."""
    if not (settings.informer_api_key and settings.informer_security_code):
        return McpServer(
            name=NAME,
            connection=None,
            unavailable_reason="INFORMER_API_KEY and INFORMER_SECURITY_CODE are not set",
        )
    return McpServer(
        name=NAME,
        connection={
            "command": sys.executable,
            "args": ["-m", "informer_mcp"],
            "transport": "stdio",
            "env": {
                **os.environ,
                "INFORMER_API_KEY": settings.informer_api_key,
                "INFORMER_SECURITY_CODE": settings.informer_security_code,
            },
        },
        read_allowlist=READ_TOOLS,
    )


def informer_fixture_server() -> McpServer:
    """The same server against the Fixture world's fake Informer API (fixture_world.informer)."""
    return McpServer(
        name=NAME,
        connection={
            "command": sys.executable,
            "args": ["-m", "fixture_world.informer"],
            "transport": "stdio",
            # Passes FIXTURE_WORLD_TODAY through when set (the stdio client's default env drops it).
            "env": {**os.environ},
        },
        read_allowlist=READ_TOOLS,
    )
