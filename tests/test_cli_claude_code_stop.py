"""A Claude Code call that can't produce a turn stops the agent CLI with its message, not a traceback."""
import pytest
from _cli_harness import cli_run  # noqa: F401

from agent.claude_code_model import ClaudeCodeError

STOP = "Claude subscription usage limit reached; resets at 3pm. Ask again after the reset."


@pytest.mark.asyncio
async def test_a_claude_code_stop_shows_its_message_and_exits(cli_run, capsys):
    seen, start = cli_run

    def stopped(messages):
        raise ClaudeCodeError(STOP)

    with pytest.raises(SystemExit) as exit_:
        await start([stopped])

    assert exit_.value.code == 1
    out, err = capsys.readouterr()
    assert f"Stopped: {STOP}" in out
    assert "Traceback" not in out + err
    assert seen["flushed"] == 1
