# src/agent/tools/informer.py
"""The Informer MCP server (src/informer_mcp, ADR-006): against real Informer, or the Fixture world.

Both are loaded under the same name ("informer"), with the same classification, so the
agent sees the same tools against either.
"""

import re
import sys

from agent.config import Settings, settings as default_settings
from agent.tools import ms365_mcp
from agent.tools.mcp_environment import fixture_environment, inherited, system_environment
from agent.tools.mcp_loader import McpServer
from informer_mcp.client import TRANSIENT_ERROR_PREFIX
from informer_mcp.config import InformerSettings

NAME = "informer"

# The server is ours and exposes no write endpoints (ADR-006), but tools are still listed
# by name rather than trusting readOnlyHint: a tool added to the server without being
# listed here is a gated Write action until someone checks it (ADR-010).
READ_TOOLS = frozenset({
    "list_relations",
    "get_relation",
    "list_sales_invoices",
    "get_sales_invoice",
    "trial_balance",
    "check_purchase_invoice",
    "revenue",
    "vat_position",
})

# Over MCP a transient Informer failure (unreachable, 429, 5xx) arrives only as tool-error
# text starting with this prefix; the loader turns it into a retryable error.
TRANSIENT_ERRORS = (re.escape(TRANSIENT_ERROR_PREFIX),)


def _informer_setting_names() -> list[str]:
    """Environment names of the Informer server's own settings, read from its settings model.

    Derived rather than listed, so a setting added to the server is passed on without a change here.
    """
    prefix = InformerSettings.model_config["env_prefix"]
    return [prefix + name.upper() for name in InformerSettings.model_fields]


def _ms365_settings(settings: Settings) -> dict[str, str]:
    """What the Informer server's e-mail transport needs to start its own MS365 server (ADR-019):
    the agent's one package pin and its Microsoft login's IDs (identifiers, not secrets)."""
    values = {
        "INFORMER_MS365_PACKAGE": ms365_mcp.PACKAGE,
        "INFORMER_MS365_CLIENT_ID": settings.ms365_mcp_client_id,
        "INFORMER_MS365_TENANT_ID": settings.ms365_mcp_tenant_id,
        "INFORMER_MS365_EXPECTED_USERNAME": settings.ms365_mcp_expected_username,
    }
    return {name: value for name, value in values.items() if value}


def _downloads_dir(settings: Settings) -> dict[str, str]:
    """The Downloads folder the agent's Processed check uses (INFORMER_DOWNLOADS_DIR, also from the
    agent's `.env`), so the server checks the same folder: the stand-in reads no `.env`, and the
    agent's settings may not be the ones the real server would read itself."""
    return {"INFORMER_DOWNLOADS_DIR": settings.informer_downloads_dir} if settings.informer_downloads_dir else {}


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
                **system_environment(),
                # Its MS365 settings come only from the agent's own login (_ms365_settings), never the shell.
                **inherited(n for n in _informer_setting_names() if not n.startswith("INFORMER_MS365_")),
                "INFORMER_API_KEY": settings.informer_api_key,
                "INFORMER_SECURITY_CODE": settings.informer_security_code,
                **_ms365_settings(settings),
                **_downloads_dir(settings),
            },
        },
        read_allowlist=READ_TOOLS,
        transient_errors=TRANSIENT_ERRORS,
    )


def informer_fixture_server(settings: Settings = default_settings) -> McpServer:
    """The same server against the Fixture world's fake Informer API (fixture_world.informer)."""
    return McpServer(
        name=NAME,
        connection={
            "command": sys.executable,
            "args": ["-m", "fixture_world.informer"],
            "transport": "stdio",
            # The Fixture world's own settings and the system basics: never the real Informer settings.
            "env": {
                **fixture_environment(),
                **_downloads_dir(settings),
                "INFORMER_MS365_PACKAGE": ms365_mcp.PACKAGE,  # for the login command it names
            },
        },
        read_allowlist=READ_TOOLS,
        transient_errors=TRANSIENT_ERRORS,
    )
