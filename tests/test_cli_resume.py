"""Resume a Conversation: `--resume <id>` or bare `--resume` continues a thread from an earlier session."""
import pytest
from _cli_harness import cli_run  # noqa: F401
from langchain_core.messages import AIMessage

from agent.claude_code_model import ClaudeCodeError


def _conversation_id(out):
    return next(line for line in out.splitlines() if line.startswith("Conversation ")).removeprefix("Conversation ")


def _shows(shown, reply):
    def answer(messages):
        shown.extend(m.content for m in messages)
        return AIMessage(content=reply)
    return answer


@pytest.mark.asyncio
async def test_resume_with_an_id_continues_that_thread(cli_run, capsys):
    seen, start = cli_run
    await start(["Monday is free."], "--fixtures", "Is Monday free?")
    thread_id = _conversation_id(capsys.readouterr().out)

    shown = []
    await start([_shows(shown, "Yes, also free.")], "--fixtures", "--resume", thread_id, "And Tuesday?")

    assert "Is Monday free?" in shown and "Monday is free." in shown and "And Tuesday?" in shown
    assert _conversation_id(capsys.readouterr().out) == thread_id


@pytest.mark.asyncio
async def test_a_bare_resume_continues_the_most_recent_conversation(cli_run, capsys):
    seen, start = cli_run
    await start(["Monday is free."], "--fixtures", "Is Monday free?")
    capsys.readouterr()
    await start(["Ann is in."], "--fixtures", "Is Ann in?")
    latest = _conversation_id(capsys.readouterr().out)

    shown = []
    await start([_shows(shown, "Bob too.")], "--fixtures", "--resume", "And Bob?")

    assert "Is Ann in?" in shown and "And Bob?" in shown and "Is Monday free?" not in shown
    assert _conversation_id(capsys.readouterr().out) == latest


@pytest.mark.asyncio
async def test_resuming_an_unknown_id_stops_with_a_clear_message(cli_run, capsys):
    seen, start = cli_run
    unknown = "0b9c6a51-6f43-4b8e-9d4e-5a3f1c2d7e88"
    with pytest.raises(SystemExit) as stop:
        await start([], "--fixtures", "--resume", unknown)

    assert stop.value.code == 1
    assert f"Cannot resume: no Conversation {unknown} in the Fixture world." in capsys.readouterr().out


@pytest.mark.asyncio
async def test_a_bare_resume_with_no_conversations_stops_with_a_clear_message(cli_run, capsys):
    seen, start = cli_run
    with pytest.raises(SystemExit) as stop:
        await start([], "--fixtures", "--resume")

    assert stop.value.code == 1
    assert "Cannot resume: there is no Conversation in the Fixture world yet." in capsys.readouterr().out


@pytest.mark.asyncio
async def test_real_and_fixture_world_conversations_are_kept_apart(cli_run, capsys):
    seen, start = cli_run
    await start(["Revenue is up."], "--fixtures", "How is revenue?")
    fixture_id = _conversation_id(capsys.readouterr().out)

    with pytest.raises(SystemExit):
        await start([], "--resume")
    assert "Cannot resume: there is no Conversation in real data yet." in capsys.readouterr().out

    with pytest.raises(SystemExit):
        await start([], "--resume", fixture_id)
    assert f"no Conversation {fixture_id} in real data" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_a_resumed_conversations_run_log_entry_covers_every_session(cli_run, capsys):
    seen, start = cli_run
    await start(["Monday is free."], "Is Monday free?")
    thread_id = _conversation_id(capsys.readouterr().out)
    await start(["Tuesday too."], "--resume", thread_id, "And Tuesday?")

    [second] = seen["logged"]  # one entry for the thread: the second session replaced the first
    assert second.thread_id == thread_id
    assert second.user_input == "Is Monday free?\nAnd Tuesday?"
    assert second.final_output == "Monday is free.\nTuesday too."


@pytest.mark.asyncio
async def test_a_resumed_conversations_run_log_entry_keeps_an_earlier_sessions_failure(cli_run, capsys):
    seen, start = cli_run

    def stopped(messages):
        raise ClaudeCodeError("usage limit reached")

    await start([stopped], "Is Monday free?")
    thread_id = _conversation_id(capsys.readouterr().out)
    await start(["Tuesday is free."], "--resume", thread_id, "And Tuesday?")

    [second] = seen["logged"]
    assert second.outcome == "error"
    assert second.error_message == "ClaudeCodeError: usage limit reached"


def test_the_usage_line_mentions_resume(capsys):
    import agent.cli as cli

    with pytest.raises(SystemExit):
        cli._parse_args(["--fixture"])
    assert "[--resume [<id>]]" in capsys.readouterr().out
