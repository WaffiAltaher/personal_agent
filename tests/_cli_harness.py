"""Shared CLI harness for the concept 4-5 killing tests: everything outside the run is replaced."""
import sys

import pytest
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage
from langchain_core.tools import tool

import agent.cli as cli
import agent.graph as graph
from agent.tools.classification import read_tool, write_action


def type_lines(monkeypatch, lines):
    """Stand in for the owner at the `> ` prompt: each read returns the next line, then Ctrl-D (EOF).
    A line that is an exception (KeyboardInterrupt for Ctrl-C) is raised instead.

    Returns the prompts the CLI showed, in order."""
    remaining = list(lines)
    prompts = []

    def read_line(prompt):
        prompts.append(prompt)
        if not remaining:
            raise EOFError
        line = remaining.pop(0)
        if isinstance(line, BaseException):
            raise line
        return line

    monkeypatch.setattr(cli, "_read_line", read_line)
    return prompts


class RecordingHandler(BaseCallbackHandler):
    """Stands in for Langfuse's CallbackHandler: records which tools it saw start."""
    def __init__(self):
        self.tools_started = []

    def on_tool_start(self, serialized, input_str, **kwargs):
        self.tools_started.append((serialized or {}).get("name") or kwargs.get("name"))


@pytest.fixture
def cli_run(monkeypatch, tmp_path, scripted_model, startup_login_checks_pass):
    # Real sqlite checkpoint files in a temp dir: Conversations persist across start() calls.
    monkeypatch.setattr(graph, "CHECKPOINT_DB", str(tmp_path / "hitl.db"))
    monkeypatch.setattr(graph, "FIXTURE_CHECKPOINT_DB", str(tmp_path / "fixtures.db"))
    seen = {"ran": [], "flushed": 0, "handler": RecordingHandler(), "configs": [], "logged": [],
            "tools": []}  # a test adds its own tools here before start()

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
        return [send_mail, lookup, *seen["tools"]], []

    class EpisodicMemory:
        def log_run(self, run):
            seen["logged"].append(run)

    def start(replies, *args, lines=()):
        """Run main() with `args` (default: a question against the Fixture world), then `lines` at `> `."""
        monkeypatch.setattr(cli, "create_chat_model", lambda: scripted_model(replies))
        monkeypatch.setattr(cli, "verify_connection", lambda: True)
        monkeypatch.setattr(cli, "get_callback_handler", lambda **kwargs: seen["handler"])
        monkeypatch.setattr(cli, "load_all_tools", load_all_tools)
        monkeypatch.setattr(cli, "get_checkpointer", graph.get_checkpointer)
        monkeypatch.setattr(graph, "get_episodic_memory", lambda: EpisodicMemory())
        monkeypatch.setattr(cli, "flush_traces", lambda: seen.__setitem__("flushed", seen["flushed"] + 1))
        seen["prompts"] = type_lines(monkeypatch, lines)
        monkeypatch.setattr(sys, "argv", ["agent.cli", *(args or ("--fixtures", "Mail Ann, then Bob."))])
        return cli.main()
    return seen, start


def mail(to, call_id):
    return AIMessage(content="", tool_calls=[{"id": call_id, "name": "send_mail", "args": {"to": to}}])
