"""
tests/test_fixture_world_ms365_concurrency.py

The agent's MCP client starts a fresh stand-in MS365 process per tool call, so concurrent
tool calls are concurrent processes sharing the Drafts file and the failure-switch file.
These tests start several processes at once (each waits for a "go" file, then acts) and
check that the shared state stays consistent: every Draft gets its own id, and a failure
switched on for N uses fails exactly N calls.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from fixture_world.ms365 import DRAFTS_ENV, Failure, FailureSwitch, recorded_drafts

PROCESSES = 16

_WAIT_FOR_GO = """
go = sys.argv[1]
while not os.path.exists(go):
    pass
"""

# Each script imports first, then waits, so the processes act as close together as possible.
_CREATE_DRAFT = """
import asyncio, os, sys
from fixture_world.ms365 import create_server
server = create_server()
""" + _WAIT_FOR_GO + """
asyncio.run(server.call_tool("create-draft-email", {"body": {"subject": "Reminder"}}))
"""

_TAKE_FAILURE = """
import os, sys
from fixture_world.ms365 import Failure, take_failure
""" + _WAIT_FOR_GO + """
print(take_failure(Failure.TRANSIENT) or "")
"""


def _run_at_once(script: str, go: Path, env: dict[str, str]) -> list[str]:
    """Start PROCESSES copies of `script`, release them together, and return their stdout."""
    procs = [
        subprocess.Popen([sys.executable, "-c", script, str(go)], env={**os.environ, **env},
                         stdout=subprocess.PIPE, text=True)
        for _ in range(PROCESSES)
    ]
    time.sleep(2)  # let every process import and reach the wait
    go.touch()
    outputs = [p.communicate(timeout=60)[0] for p in procs]
    assert all(p.returncode == 0 for p in procs)
    return outputs


def test_concurrent_draft_calls_each_get_their_own_draft_id(tmp_path):
    drafts = tmp_path / "drafts.jsonl"

    _run_at_once(_CREATE_DRAFT, tmp_path / "go", {DRAFTS_ENV: str(drafts), "FIXTURE_WORLD_TODAY": "2026-10-07"})

    ids = [draft["id"] for draft in recorded_drafts(drafts)]
    assert len(ids) == PROCESSES
    assert len(set(ids)) == PROCESSES, ids
    # still numbered in order of creation
    assert sorted(ids) == [f"AAMkAGZpeHR1cmUADRAFT{n:02d}" for n in range(1, PROCESSES + 1)]
    assert all(json.loads(line) for line in drafts.read_text().splitlines())


def test_a_failure_for_n_uses_fails_exactly_n_concurrent_calls(tmp_path):
    switch = FailureSwitch(tmp_path / "ms365-failure")
    switch.set(Failure.TRANSIENT, times=3)

    outputs = _run_at_once(_TAKE_FAILURE, tmp_path / "go", switch.env)

    assert sum(out.strip() == Failure.TRANSIENT for out in outputs) == 3
