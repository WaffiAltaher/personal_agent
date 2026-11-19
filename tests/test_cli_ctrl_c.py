"""Ctrl-C cancels the running turn and returns to `> `; at a prompt it only clears the line."""
import asyncio
import signal

import pytest
from _cli_harness import cli_run, type_lines  # noqa: F401
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import tool

import agent.cli as cli
from agent.tools.classification import read_tool


@read_tool
@tool("slow_lookup")
async def slow_lookup(query: str) -> str:
    """Looks something up, slowly: the owner presses Ctrl-C while it runs."""
    signal.raise_signal(signal.SIGINT)
    await asyncio.sleep(5)
    return "found it"


def slow(call_id):
    return AIMessage(content="", tool_calls=[{"id": call_id, "name": "slow_lookup", "args": {"query": "x"}}])


@pytest.mark.asyncio
async def test_ctrl_c_during_a_tool_call_cancels_the_turn_and_a_follow_up_still_works(cli_run, capsys):
    seen, start = cli_run
    seen["tools"].append(slow_lookup)
    shown = []

    def answer(messages):
        shown.extend(messages)
        return AIMessage(content="Here you go.")

    await start([slow("c1"), answer], "--fixtures", "Look it up.", lines=["Try again?"])

    out = capsys.readouterr().out
    assert "Interrupted." in out and "Here you go." in out
    assert seen["prompts"] == ["> ", "> "]
    [closed] = [m for m in shown if isinstance(m, ToolMessage) and m.tool_call_id == "c1"]
    assert "interrupted by the owner" in closed.content.lower()
    assert "Look it up." in [m.content for m in shown]  # same Conversation


@pytest.mark.asyncio
async def test_ctrl_c_at_the_prompt_clears_the_line_and_prompts_again(cli_run, capsys):
    seen, start = cli_run
    await start(["Hello."], "--fixtures", lines=[KeyboardInterrupt(), "hi"])

    assert seen["prompts"] == ["> ", "> ", "> "]
    assert "Hello." in capsys.readouterr().out


def test_ctrl_c_at_the_approval_prompt_clears_the_line_and_asks_again(monkeypatch):
    prompts = type_lines(monkeypatch, [KeyboardInterrupt(), "approve"])

    assert cli._prompt_decision() == "approve"
    assert prompts == ["Your decision: ", "Your decision: "]
