"""
tests/test_cli_fixtures.py

`python -m agent.cli --fixtures` runs against the Fixture world with one "today": the date the
model is told is the Fixture world's pinned date, and the stand-in servers started for the
run see the same date. Everything outside the run is replaced: the model is scripted, the
tools are recorded instead of started, the checkpointer is in memory, nothing is traced or
written to memory.
"""

import os
import sys
from contextlib import asynccontextmanager

import pytest
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver

import agent.cli as cli

import agent.startup as startup


@pytest.fixture
def run_cli(monkeypatch, scripted_model, startup_login_checks_pass):
    """Run the CLI's main() with the given arguments; returns what the run saw."""
    seen = {"system": [], "env_today_at_tool_load": [], "logged_to_memory": []}

    def reply(messages):
        seen["system"].append(messages[0].content)
        return AIMessage(content="Today is Wednesday.")

    async def load_all_tools(*, fixtures=False):
        seen["env_today_at_tool_load"].append(os.environ.get("FIXTURE_WORLD_TODAY"))
        return [], []

    @asynccontextmanager
    async def get_checkpointer(db_path=None):
        yield InMemorySaver()

    monkeypatch.setattr(cli, "create_chat_model", lambda: scripted_model([reply]))
    monkeypatch.setattr(startup, "verify_connection", lambda: True)
    monkeypatch.setattr(cli, "get_callback_handler", lambda **kwargs: BaseCallbackHandler())
    monkeypatch.setattr(cli, "load_all_tools", load_all_tools)
    monkeypatch.setattr(cli, "get_checkpointer", get_checkpointer)
    monkeypatch.setattr(
        cli,
        "log_run_to_memory",
        lambda result, user_input, **kwargs: seen["logged_to_memory"].append(user_input),
    )
    monkeypatch.setattr(cli, "flush_traces", lambda: None)
    # Start without a pinned date, and restore the environment afterwards.
    monkeypatch.setenv("FIXTURE_WORLD_TODAY", "")
    monkeypatch.delenv("FIXTURE_WORLD_TODAY")

    async def run(*args):
        monkeypatch.setattr(sys, "argv", ["agent.cli", *args])
        await cli.main()
        return seen
    return run


@pytest.mark.asyncio
async def test_fixtures_mode_tells_the_model_the_fixture_worlds_date_and_pins_it_for_the_stand_ins(run_cli):
    seen = await run_cli("--fixtures", "What day is it?")

    assert "Current date/time: 2026-10-07T09:00:00+02:00" in seen["system"][0]
    assert seen["env_today_at_tool_load"] == ["2026-10-07"]


@pytest.mark.asyncio
async def test_fixtures_mode_follows_a_date_pinned_with_the_knob(run_cli, monkeypatch):
    monkeypatch.setenv("FIXTURE_WORLD_TODAY", "2026-10-09")

    seen = await run_cli("--fixtures", "What day is it?")

    assert "Current date/time: 2026-10-09T09:00:00+02:00" in seen["system"][0]
    assert seen["env_today_at_tool_load"] == ["2026-10-09"]


@pytest.mark.asyncio
async def test_without_fixtures_the_date_is_not_pinned(run_cli):
    seen = await run_cli("What day is it?")

    assert "T09:00:00+02:00" not in seen["system"][0]  # the real time, to the microsecond
    assert seen["env_today_at_tool_load"] == [None]


@pytest.mark.asyncio
async def test_fixtures_mode_writes_nothing_to_the_owners_memory(run_cli):
    seen = await run_cli("--fixtures", "What day is it?")

    assert seen["logged_to_memory"] == []


@pytest.mark.asyncio
async def test_without_fixtures_the_run_is_logged_to_memory(run_cli):
    seen = await run_cli("What day is it?")

    assert seen["logged_to_memory"] == ["What day is it?"]
