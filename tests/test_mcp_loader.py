"""
tests/test_mcp_loader.py

The MCP loader starts every configured server; each is optional and isolated. A server
that isn't configured or fails to start is reported in a notice, and the rest still load.
"""

import json
import os
import re
from pathlib import Path

import pytest

from agent.config import Settings
from agent.tools.mcp_environment import SYSTEM_VARIABLES
from agent.tools.mcp_loader import McpServer, load_mcp_tools
from agent.tools.informer import informer_fixture_server, informer_server
from fixture_world.informer_api import FakeInformerApi
from agent.tools.ms365_mcp import EXPOSED_TOOLS, READ_TOOLS, ms365_fixture_server, ms365_server

REPO_ROOT = Path(__file__).resolve().parents[1]

# Variables a shell or the .env may hold, that no MCP server should ever receive.
SECRETS = {
    "ANTHROPIC_API_KEY": "sk-ant-decoy",
    "GOOGLE_API_KEY": "google-decoy",
    "TAVILY_API_KEY": "tavily-decoy",
    "LANGFUSE_SECRET_KEY": "langfuse-decoy",
    "AGENT_DECOY_SECRET": "made-up-decoy",
    "MS365_MCP_USE_KEYTAR": "false",
    "ENABLED_TOOLS": ".*",
    "INFORMER_NOT_A_SETTING": "decoy",  # Informer's prefix, but not one of its settings
}


def _real_settings() -> Settings:
    return Settings(_env_file=None, ms365_mcp_client_id="client", ms365_mcp_tenant_id="tenant",
                    informer_api_key="informer-key", informer_security_code="informer-code")


def _connections(settings: Settings) -> dict[str, dict]:
    """The connection each server builder returns, by name."""
    return {
        "ms365": ms365_server(settings).connection,
        "ms365 stand-in": ms365_fixture_server().connection,
        "informer": informer_server(settings).connection,
        "informer stand-in": informer_fixture_server().connection,
    }


@pytest.fixture
def clean_environment(monkeypatch):
    """No MS365, Informer or Fixture-world variable from the developer's shell; restored afterwards."""
    for key in list(os.environ):
        if key.startswith(("MS365_MCP_", "INFORMER_", "FIXTURE_WORLD_")):
            monkeypatch.delenv(key)
    return monkeypatch


def test_no_server_receives_a_secret_from_the_environment(clean_environment):
    for key, value in SECRETS.items():
        clean_environment.setenv(key, value)

    for name, connection in _connections(_real_settings()).items():
        assert set(connection["env"]) & set(SECRETS) == set(), name


def test_each_server_receives_its_own_settings_and_nothing_else(clean_environment):
    clean_environment.setenv("FIXTURE_WORLD_TODAY", "2026-10-07")
    clean_environment.setenv("INFORMER_PAGE_SIZE", "37")  # a setting the Informer server reads itself
    for key, value in SECRETS.items():
        clean_environment.setenv(key, value)

    own = {
        name: set(connection["env"]) - SYSTEM_VARIABLES
        for name, connection in _connections(_real_settings()).items()
    }

    assert own == {
        "ms365": {"MS365_MCP_CLIENT_ID", "MS365_MCP_TENANT_ID"},
        "ms365 stand-in": {"FIXTURE_WORLD_TODAY"},
        "informer": {"INFORMER_API_KEY", "INFORMER_SECURITY_CODE", "INFORMER_PAGE_SIZE"},
        "informer stand-in": {"FIXTURE_WORLD_TODAY"},
    }


def test_ms365_servers_start_outside_the_repo(clean_environment):
    connections = _connections(_real_settings())
    for name in ("ms365", "ms365 stand-in"):
        cwd = Path(connections[name]["cwd"]).resolve()

        assert cwd.is_dir(), name
        assert not cwd.is_relative_to(REPO_ROOT), name  # so the server can't read the repo's .env


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
    monkeypatch.setenv("MS365_MCP_USE_KEYTAR", "false")  # set first, so the assertion below can fail
    monkeypatch.setenv("ENABLED_TOOLS", ".*")  # would override --enabled-tools on the server
    settings = Settings(_env_file=None, ms365_mcp_client_id="client", ms365_mcp_tenant_id="tenant",
                        ms365_mcp_expected_username="jendo@example.com")

    connection = ms365_server(settings).connection

    args = connection["args"]
    assert "@softeria/ms-365-mcp-server@0.159.1" in args
    assert "--read-only" not in args and "--preset" not in args
    # The server tests each tool name against the pattern case-insensitively, without anchoring.
    pattern = re.compile(args[args.index("--enabled-tools") + 1], re.IGNORECASE)
    # download-bytes-to-file is enabled for the agent's own ms365_save_attachment (ADR-015); it is a
    # GET, so it asks for no new Graph scope.
    for allowed in ("create-draft-email", "create-reply-draft", "list-mail-messages", "get-calendar-view",
                    "list-mail-attachments", "download-bytes-to-file"):
        assert pattern.search(allowed)
    for forbidden in ("send-mail", "send-draft-message", "reply-mail-message", "create-reply-all-draft",
                      "create-forward-draft", "delete-mail-message", "move-mail-message", "update-mail-message",
                      "create-calendar-event", "create-mail-rule", "create-mail-folder",
                      "update-my-calendar-permission", "add-mail-attachment", "delete-mail-attachment",
                      "login", "list-accounts"):
        assert not pattern.search(forbidden), forbidden

    env = connection["env"]
    assert env["MS365_MCP_EXPECTED_USERNAME"] == "jendo@example.com"
    assert "ENABLED_TOOLS" not in env
    assert "MS365_MCP_USE_KEYTAR" not in env  # the macOS keychain token cache stays enabled


def test_download_bytes_to_file_is_never_exposed_or_read_classified():
    # The server annotates it readOnlyHint although it writes a local file: only the allowlist counts.
    assert "download-bytes-to-file" not in READ_TOOLS
    assert "download-bytes-to-file" not in EXPOSED_TOOLS
    assert "list-mail-attachments" in READ_TOOLS


def test_expected_ms365_username_is_optional(monkeypatch):
    monkeypatch.delenv("MS365_MCP_EXPECTED_USERNAME", raising=False)
    settings = Settings(_env_file=None, ms365_mcp_client_id="client", ms365_mcp_tenant_id="tenant")

    assert "MS365_MCP_EXPECTED_USERNAME" not in ms365_server(settings).connection["env"]


@pytest.mark.asyncio
async def test_without_informer_credentials_the_agent_starts_with_a_notice():
    settings = Settings(_env_file=None, informer_api_key=None, informer_security_code=None)

    tools, notices = await load_mcp_tools([informer_server(settings), ms365_fixture_server()])

    assert notices == ["informer tools unavailable: INFORMER_API_KEY and INFORMER_SECURITY_CODE are not set"]
    assert not any(t.name.startswith("informer_") for t in tools)
    assert "ms365_get-calendar-view" in {t.name for t in tools}


@pytest.mark.asyncio
async def test_configured_informer_server_reaches_informer_with_the_credentials(monkeypatch):
    with FakeInformerApi() as fake:
        monkeypatch.setenv("INFORMER_BASE_URL", fake.base_url)
        settings = Settings(_env_file=None, informer_api_key=fake.api_key, informer_security_code=fake.security_code)

        tools, notices = await load_mcp_tools([informer_server(settings)])
        list_relations = {t.name: t for t in tools}["informer_list_relations"]
        result = await list_relations.ainvoke({"search": "Noordzee"})

    assert notices == []
    text = result if isinstance(result, str) else "".join(block["text"] for block in result)
    assert [r["name"] for r in json.loads(text)["relations"]] == ["Noordzee Advies"]
