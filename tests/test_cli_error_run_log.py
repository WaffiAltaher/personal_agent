"""CLI records an error outcome when the conversation raises."""

import sys
from contextlib import asynccontextmanager

import pytest
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver

import agent.cli as cli


@pytest.mark.asyncio
async def test_cli_logs_error_outcome_and_flushes_traces(monkeypatch, scripted_model):
    logged = []
    flushed = {"n": 0}

    @asynccontextmanager
    async def get_checkpointer():
        yield InMemorySaver()

    async def load_all_tools(*, fixtures=False):
        return [], []

    def capture_log(result, user_input, **kwargs):
        logged.append({"error": kwargs.get("error")})

    monkeypatch.setattr(cli, "create_chat_model", lambda: scripted_model([AIMessage(content="x")]))
    monkeypatch.setattr(cli, "check_google_login", lambda: None)
    monkeypatch.setattr(cli, "verify_connection", lambda: False)
    monkeypatch.setattr(cli, "get_checkpointer", get_checkpointer)
    monkeypatch.setattr(cli, "load_all_tools", load_all_tools)
    monkeypatch.setattr(cli, "log_run_to_memory", capture_log)
    monkeypatch.setattr(cli, "flush_traces", lambda: flushed.__setitem__("n", flushed["n"] + 1))
    monkeypatch.setattr(
        cli,
        "run_conversation",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    monkeypatch.setattr(sys, "argv", ["agent.cli", "hello"])

    with pytest.raises(RuntimeError, match="boom"):
        await cli.main()

    assert logged[0]["error"] == "RuntimeError: boom"
    assert flushed["n"] == 1
