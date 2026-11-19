"""A known failure (Claude Code call that can't produce a turn, step limit) keeps the session going."""
import pytest
from _cli_harness import cli_run  # noqa: F401
from langchain_core.messages import AIMessage
from langgraph.errors import GraphRecursionError

from agent.claude_code_model import ClaudeCodeError

STOP = "Claude subscription usage limit reached; resets at 3pm. Ask again after the reset."


@pytest.mark.asyncio
async def test_a_claude_code_stop_shows_its_message_and_the_next_question_continues(cli_run, capsys):
    seen, start = cli_run

    def stopped(messages):
        raise ClaudeCodeError(STOP)

    await start([stopped, AIMessage(content="Second answer.")], "first?", lines=["again?"])

    out, err = capsys.readouterr()
    assert f"Stopped: {STOP}" in out
    assert "Second answer." in out
    assert "Traceback" not in out + err
    assert seen["prompts"] == ["> ", "> "]
    assert seen["flushed"] == 1
    # One Conversation: the run log entry holds both questions and records the failure.
    assert len(seen["logged"]) == 1
    assert seen["logged"][0].outcome == "error"
    assert seen["logged"][0].error_message == f"ClaudeCodeError: {STOP}"


@pytest.mark.asyncio
async def test_the_step_limit_keeps_the_session(cli_run, capsys):
    seen, start = cli_run

    def too_long(messages):
        raise GraphRecursionError("limit")

    await start([too_long, AIMessage(content="Narrow answer.")], lines=["narrower?"])

    out, _ = capsys.readouterr()
    assert "Stopped: the agent hit its step limit" in out
    assert "Narrow answer." in out
    assert seen["prompts"] == ["> ", "> "]
