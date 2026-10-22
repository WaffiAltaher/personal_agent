"""
tests/test_ms365_startup_once.py

Startup reuses one Microsoft 365 session for loading tools and checking the login, so the
server starts once, not twice. The seam is the stdio launch of the server (a process per
session); the MS365 stand-in runs for real, so the login check and tool loading are real.
"""

import contextlib

import pytest

import langchain_mcp_adapters.sessions as adapter_sessions
from agent.tools.mcp_loader import load_mcp_tools
from agent.tools.ms365_mcp import ms365_fixture_server


@pytest.fixture
def server_launches(monkeypatch):
    """Names of the servers started (by command and args), in order."""
    launches = []
    real_stdio_client = adapter_sessions.stdio_client

    @contextlib.asynccontextmanager
    async def counting_stdio_client(params, *args, **kwargs):
        launches.append((params.command, tuple(params.args)))
        async with real_stdio_client(params, *args, **kwargs) as streams:
            yield streams

    monkeypatch.setattr(adapter_sessions, "stdio_client", counting_stdio_client)
    return launches


@pytest.mark.anyio
async def test_startup_launches_the_ms365_server_once(server_launches):
    tools, notices = await load_mcp_tools([ms365_fixture_server()])

    assert notices == []  # logged in, tools loaded
    assert tools  # the login check didn't cost the tools
    assert len(server_launches) == 1


@pytest.mark.anyio
async def test_tools_loaded_at_startup_still_work_after_the_startup_session_closed(server_launches):
    tools, _ = await load_mcp_tools([ms365_fixture_server()])
    by_name = {tool.name: tool for tool in tools}

    result = await by_name["ms365_list-outlook-contacts"].ainvoke({})

    assert result  # a run's tool calls don't depend on the closed startup session
