"""
tests/test_mcp_loader.py

The MCP loader starts every configured server; each is optional and isolated. A server
that isn't configured or fails to start is reported in a notice, and the rest still load.
"""

import re

import pytest

from agent.config import Settings
from agent.tools.mcp_loader import McpServer, load_mcp_tools
from agent.tools.ms365_mcp import ms365_fixture_server, ms365_server


@pytest.mark.asyncio
async def test_unavailable_servers_are_skipped_with_a_notice():
    servers = [
        McpServer(name="unconfigured", connection=None, unavailable_reason="UNCONFIGURED_API_KEY is not set"),
        McpServer(name="broken", connection={
            "command": "/nonexistent/mcp-server", "args": [], "transport": "stdio",
        }),
        ms365_fixture_server(),
    ]

    tools, notices = await load_mcp_tools(servers)

    assert "ms365_get-calendar-view" in {t.name for t in tools}
    assert not any(t.name.startswith(("unconfigured_", "broken_")) for t in tools)
    assert len(notices) == 2
    assert notices[0] == "unconfigured tools unavailable: UNCONFIGURED_API_KEY is not set"
    assert notices[1].startswith("broken tools unavailable: the server failed to start")


def test_real_ms365_server_is_unavailable_without_credentials():
    settings = Settings(_env_file=None, ms365_mcp_client_id=None, ms365_mcp_tenant_id=None)

    server = ms365_server(settings)

    assert server.connection is None
    assert "MS365_MCP_CLIENT_ID" in server.unavailable_reason


def test_real_ms365_server_is_pinned_and_offers_drafts_but_no_other_writes(monkeypatch):
    monkeypatch.delenv("MS365_MCP_USE_KEYTAR", raising=False)
    monkeypatch.setenv("ENABLED_TOOLS", ".*")  # would override --enabled-tools on the server
    settings = Settings(_env_file=None, ms365_mcp_client_id="client", ms365_mcp_tenant_id="tenant",
                        ms365_mcp_expected_username="jendo@example.com")

    connection = ms365_server(settings).connection

    args = connection["args"]
    assert "@softeria/ms-365-mcp-server@0.159.1" in args
    assert "--read-only" not in args and "--preset" not in args
    # The server tests each tool name against the pattern case-insensitively, without anchoring.
    pattern = re.compile(args[args.index("--enabled-tools") + 1], re.IGNORECASE)
    for allowed in ("create-draft-email", "create-reply-draft", "list-mail-messages", "get-calendar-view"):
        assert pattern.search(allowed)
    for forbidden in ("send-mail", "send-draft-message", "reply-mail-message", "create-reply-all-draft",
                      "create-forward-draft", "delete-mail-message", "move-mail-message", "update-mail-message",
                      "create-calendar-event", "create-mail-rule", "create-mail-folder",
                      "update-my-calendar-permission", "download-bytes-to-file", "login", "list-accounts"):
        assert not pattern.search(forbidden), forbidden

    env = connection["env"]
    assert env["MS365_MCP_EXPECTED_USERNAME"] == "jendo@example.com"
    assert "ENABLED_TOOLS" not in env
    assert "MS365_MCP_USE_KEYTAR" not in env  # the macOS keychain token cache stays enabled


def test_expected_ms365_username_is_optional(monkeypatch):
    monkeypatch.delenv("MS365_MCP_EXPECTED_USERNAME", raising=False)
    settings = Settings(_env_file=None, ms365_mcp_client_id="client", ms365_mcp_tenant_id="tenant")

    assert "MS365_MCP_EXPECTED_USERNAME" not in ms365_server(settings).connection["env"]
