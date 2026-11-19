"""Ctrl-C cancels the running turn and returns to `> `; at a prompt it only clears the line."""
import asyncio
import signal

import pytest
from _cli_harness import cli_run, type_lines  # noqa: F401
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import tool

import agent.cli as cli
import agent.conversation as conversation
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

    assert cli._prompt_decision() == cli.Decision("approve")
    assert prompts == ["Your decision: ", "Your decision: "]


def _close_after_a_second_ctrl_c(monkeypatch):
    """The owner presses Ctrl-C again while the cancelled turn's tool calls are being closed."""
    real = cli.close_interrupted_turn

    async def close_interrupted_turn(graph, config):
        signal.raise_signal(signal.SIGINT)
        await asyncio.sleep(5)
        await real(graph, config)

    monkeypatch.setattr(cli, "close_interrupted_turn", close_interrupted_turn)


@pytest.mark.asyncio
async def test_a_second_ctrl_c_while_closing_the_turn_ends_the_session_and_writes_the_run_log(
        cli_run, monkeypatch, capsys):
    seen, start = cli_run
    seen["tools"].append(slow_lookup)
    _close_after_a_second_ctrl_c(monkeypatch)

    await start([slow("c1")], "Look it up.", lines=["never asked"])

    out, err = capsys.readouterr()
    assert "Traceback" not in out + err
    assert seen["prompts"] == []
    [run] = seen["logged"]
    assert run.user_input == "Look it up."
    assert run.tools_called == ["slow_lookup"]  # from the thread, though the turn never finished


@pytest.mark.asyncio
async def test_tool_calls_a_second_ctrl_c_left_open_are_closed_when_the_conversation_resumes(
        cli_run, monkeypatch, capsys):
    seen, start = cli_run
    seen["tools"].append(slow_lookup)
    _close_after_a_second_ctrl_c(monkeypatch)
    await start([slow("c1")], "--fixtures", "Look it up.")
    thread_id = capsys.readouterr().out.split("Conversation ", 1)[1].split()[0]
    monkeypatch.setattr(cli, "close_interrupted_turn", conversation.close_interrupted_turn)
    shown = []

    def answer(messages):
        shown.extend(messages)
        return AIMessage(content="Here you go.")

    await start([answer], "--fixtures", "--resume", thread_id, "Try again?")

    [closed] = [m for m in shown if isinstance(m, ToolMessage) and m.tool_call_id == "c1"]
    assert "interrupted by the owner" in closed.content.lower()


@pytest.mark.asyncio
async def test_ctrl_c_between_turns_ends_the_session_and_writes_the_run_log(cli_run, monkeypatch, capsys):
    seen, start = cli_run
    monkeypatch.setattr(cli, "_display_debug_trace", lambda result: signal.raise_signal(signal.SIGINT))

    await start(["Hello."], "--debug", "hi", lines=["never asked"])

    out, err = capsys.readouterr()
    assert "Traceback" not in out + err
    assert seen["prompts"] == []
    [run] = seen["logged"]
    assert run.final_output == "Hello."
