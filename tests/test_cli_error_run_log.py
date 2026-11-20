"""CLI records an error outcome when the conversation raises."""

import sys
from contextlib import asynccontextmanager

import pytest
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver

import agent.cli as cli
import agent.turn_rules as turn_rules

import agent.startup as startup


@pytest.mark.parametrize("flags", [[], ["--fixtures"]])
@pytest.mark.asyncio
async def test_cli_logs_error_outcome_and_flushes_traces(monkeypatch, scripted_model, startup_login_checks_pass, capsys,
                                                         flags):
    logged = []
    flushed = {"n": 0}

    @asynccontextmanager
    async def get_checkpointer(db_path=None):
        yield InMemorySaver()

    async def load_all_tools(*, fixtures=False):
        return [], []

    def capture_log(result, user_input, **kwargs):
        logged.append({"error": kwargs.get("error")})

    monkeypatch.setattr(cli, "create_chat_model", lambda: scripted_model([AIMessage(content="x")]))
    monkeypatch.setattr(startup, "verify_connection", lambda: False)
    monkeypatch.setattr(cli, "get_checkpointer", get_checkpointer)
    monkeypatch.setattr(turn_rules, "get_checkpointer", get_checkpointer)
    monkeypatch.setattr(cli, "load_all_tools", load_all_tools)
    monkeypatch.setattr(turn_rules, "log_run_to_memory", capture_log)
    monkeypatch.setattr(cli, "flush_traces", lambda: flushed.__setitem__("n", flushed["n"] + 1))
    monkeypatch.setattr(
        cli,
        "run_conversation",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    monkeypatch.setattr(sys, "argv", ["agent.cli", *flags, "hello"])

    with pytest.raises(RuntimeError, match="boom"):
        await cli.main()

    # A Fixture-world run is kept out of real memory.
    assert logged == ([] if flags else [{"error": "RuntimeError: boom"}])
    # The session ends naming the command that resumes the Conversation, in the same world.
    out = capsys.readouterr().out
    conversation_id = out.split("Conversation ", 1)[1].split()[0]
    resume_cmd = f"python -m agent.cli {' '.join([*flags, '--resume'])} {conversation_id}"
    assert f"Conversation ended by an error. Resume it with: {resume_cmd}" in out
    assert flushed["n"] == 1
