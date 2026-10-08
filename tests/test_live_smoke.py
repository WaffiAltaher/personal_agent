"""Read-only live smoke check: MS365 and Informer connect, and no Draft is created.

The default suite injects Fixture-world servers, so it needs no network and no
credentials. The real check is marked live and is not part of that suite.
"""

import asyncio
import json
import os
import signal
import subprocess
import time
from pathlib import Path

import pytest

from agent.live_smoke import run_live_smoke
from agent.tools.informer import informer_fixture_server
from agent.tools.mcp_loader import McpServer
from agent.tools.ms365_mcp import ms365_fixture_server
from fixture_world.ms365 import DRAFTS_ENV, FAILURE_ENV, Failure, recorded_drafts

_RELATIONS_SEED = Path(__file__).resolve().parents[1] / "src/fixture_world/data/informer/relations.json"

# Long enough that a prompt or a stuck server would still be sleeping when the
# short smoke timeout must already have returned.
_HUNG_SLEEP_S = "120"


@pytest.mark.asyncio
async def test_logged_out_ms365_is_blocked_and_names_the_login_problem():
    server = ms365_fixture_server()
    server.connection["env"][FAILURE_ENV] = Failure.LOGGED_OUT

    result = await run_live_smoke(servers=[server])

    assert result.status == "blocked"
    assert "not logged in" in result.reason
    assert "No valid token found" in result.reason


def _sleep_pids(arg: str) -> list[int]:
    """Pids whose command is exactly `sleep <arg>`, not a shell that mentions it."""
    out = subprocess.check_output(["ps", "-ax", "-o", "pid=,command="], text=True)
    pids = []
    for line in out.splitlines():
        pid_text, _, command = line.strip().partition(" ")
        if command == f"sleep {arg}":
            pids.append(int(pid_text))
    return pids


def _kill_sleep(arg: str) -> None:
    for pid in _sleep_pids(arg):
        os.kill(pid, signal.SIGKILL)


@pytest.mark.asyncio
async def test_non_answering_server_is_blocked_and_the_sleeper_dies():
    server = McpServer(
        name="hung",
        connection={"command": "sleep", "args": [_HUNG_SLEEP_S], "transport": "stdio"},
    )
    started = time.monotonic()
    try:
        # The outer bound only stops a regression that hangs the suite. The
        # smoke check itself must return, and must have killed the sleeper.
        result = await asyncio.wait_for(
            run_live_smoke(servers=[server], timeout_s=0.5),
            timeout=15,
        )
        elapsed = time.monotonic() - started
        remaining = _sleep_pids(_HUNG_SLEEP_S)
    finally:
        _kill_sleep(_HUNG_SLEEP_S)

    assert elapsed < 15, elapsed  # well under the 120s sleep, including process-tree teardown
    assert result.status == "blocked"
    assert "keychain" in result.reason or "login" in result.reason
    assert remaining == []


@pytest.mark.asyncio
async def test_fixture_world_is_connected_and_creates_no_draft(tmp_path):
    drafts = tmp_path / "drafts.jsonl"
    ms365 = ms365_fixture_server()
    ms365.connection["env"][DRAFTS_ENV] = str(drafts)
    # Oracle: the versioned Relation seed, not a name derived the way the server maps fields.
    seeded_relation = next(
        row["company_name"] for row in json.loads(_RELATIONS_SEED.read_text()) if row["id"] == 1001
    )

    result = await run_live_smoke(servers=[ms365, informer_fixture_server()])

    assert result.status == "ok"
    assert result.reason == ""
    assert seeded_relation == "Bakkerij De Gouden Bol B.V."
    names = [row["name"] for row in result.payloads["informer_list_relations"]["relations"]]
    assert seeded_relation in names
    assert recorded_drafts(drafts) == []


@pytest.mark.asyncio
async def test_missing_env_file_is_blocked_without_echoing_secrets(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    result = await run_live_smoke(timeout_s=2)

    assert result.status == "blocked"
    assert ".env" in result.reason
    assert "test-dummy" not in result.reason
    assert os.environ["MS365_MCP_CLIENT_ID"] not in result.reason


@pytest.mark.asyncio
async def test_env_file_credentials_are_not_taken_from_the_process_environment(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # conftest puts a dummy MS365 client id in the process environment. The file omits it.
    (tmp_path / ".env").write_text(
        "GOOGLE_API_KEY=from-file\n"
        "TAVILY_API_KEY=from-file\n"
        "LANGFUSE_PUBLIC_KEY=from-file\n"
        "LANGFUSE_SECRET_KEY=from-file\n"
        "NOT_A_REAL_SETTING=secret-value\n"
    )

    result = await run_live_smoke(timeout_s=2)

    assert result.status == "failed"
    assert "MS365_MCP_CLIENT_ID" in result.reason
    assert "test-dummy" not in result.reason
    assert "secret-value" not in result.reason


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_services_answer_read_only_probes():
    """Read-only check of the owner's real MS365 and Informer. Run explicitly: pytest -m live"""
    result = await run_live_smoke()
    if result.status == "blocked":
        pytest.skip(f"blocked: {result.reason}")
    if result.status == "failed":
        pytest.fail(result.reason)
    assert result.status == "ok"
