"""Shared CLI harness for the concept 4-5 killing tests: everything outside the run is replaced."""
import sys
from contextlib import asynccontextmanager

import pytest
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver

import agent.cli as cli
from agent.tools.classification import read_tool, write_action


class RecordingHandler(BaseCallbackHandler):
    """Stands in for Langfuse's CallbackHandler: records which tools it saw start."""
    def __init__(self):
        self.tools_started = []

    def on_tool_start(self, serialized, input_str, **kwargs):
        self.tools_started.append((serialized or {}).get("name") or kwargs.get("name"))


@pytest.fixture
def cli_run(monkeypatch, scripted_model):
    seen = {"ran": [], "flushed": 0, "handler": RecordingHandler(), "configs": []}

    @write_action
    @tool("send_mail")
    async def send_mail(to: str) -> str:
        """Sends mail."""
        seen["ran"].append(to)
        return f"sent to {to}"

    @read_tool
    @tool("lookup")
    async def lookup(query: str) -> str:
        """Looks something up."""
        return "nothing found"

    async def load_all_tools(*, fixtures=False):
        return [send_mail, lookup], []

    @asynccontextmanager
    async def get_checkpointer():
        yield InMemorySaver()

    def start(replies):
        monkeypatch.setattr(cli, "create_chat_model", lambda: scripted_model(replies))
        monkeypatch.setattr(cli, "verify_connection", lambda: True)
        monkeypatch.setattr(cli, "get_callback_handler", lambda **kwargs: seen["handler"])
        monkeypatch.setattr(cli, "load_all_tools", load_all_tools)
        monkeypatch.setattr(cli, "get_checkpointer", get_checkpointer)
        monkeypatch.setattr(cli, "log_run_to_memory", lambda result, user_input, **kwargs: None)
        monkeypatch.setattr(cli, "flush_traces", lambda: seen.__setitem__("flushed", seen["flushed"] + 1))
        monkeypatch.setattr(cli, "_prompt_decision", lambda: "approve")
        monkeypatch.setattr(sys, "argv", ["agent.cli", "--fixtures", "Mail Ann, then Bob."])
        return cli.main()
    return seen, start


def mail(to, call_id):
    return AIMessage(content="", tool_calls=[{"id": call_id, "name": "send_mail", "args": {"to": to}}])
