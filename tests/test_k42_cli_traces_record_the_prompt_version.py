import sys
from contextlib import asynccontextmanager, contextmanager

import pytest
from langchain_core.callbacks import BaseCallbackHandler
from langgraph.checkpoint.memory import InMemorySaver

import agent.cli as cli
import agent.turn_rules as turn_rules

import agent.startup as startup


@pytest.mark.asyncio
async def test_a_cli_run_is_traced_with_the_prompt_version(monkeypatch, scripted_model):
    traced = []

    @contextmanager
    def propagate_attributes(**attributes):
        traced.append(attributes)
        yield

    async def load_all_tools(*, fixtures=False):
        return [], []

    @asynccontextmanager
    async def get_checkpointer(db_path=None):
        yield InMemorySaver()

    monkeypatch.setattr(cli.settings, "prompt_version", "v2")
    monkeypatch.setattr(turn_rules, "propagate_attributes", propagate_attributes)
    monkeypatch.setattr(cli, "create_chat_model", lambda: scripted_model(["ok"]))
    monkeypatch.setattr(startup, "verify_connection", lambda: True)
    monkeypatch.setattr(cli, "get_callback_handler", lambda **kwargs: BaseCallbackHandler())
    monkeypatch.setattr(cli, "load_all_tools", load_all_tools)
    monkeypatch.setattr(cli, "get_checkpointer", get_checkpointer)
    monkeypatch.setattr(turn_rules, "get_checkpointer", get_checkpointer)
    monkeypatch.setattr(turn_rules, "log_run_to_memory", lambda result, user_input: None)
    monkeypatch.setattr(cli, "flush_traces", lambda: None)
    monkeypatch.setattr(sys, "argv", ["agent.cli", "--fixtures", "hi"])

    await cli.main()

    assert traced and traced[0]["metadata"]["prompt-version"] == "v2"
