"""
tests/test_mcp_loader.py

The MCP loader starts every configured server; each is optional and isolated. A server
that isn't configured or fails to start is reported in a notice, and the rest still load.
"""

import json

import pytest

from agent.config import Settings
from agent.tools.mcp_loader import McpServer, load_mcp_tools
from agent.tools.informer import informer_server
from fixture_world.informer_api import FakeInformerApi
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
