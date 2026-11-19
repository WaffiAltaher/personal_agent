"""The CLI is a session: one Conversation, a Follow-up per line typed at `> `."""
import uuid

import pytest
from _cli_harness import cli_run, mail  # noqa: F401
from langchain_core.messages import AIMessage

import agent.cli as cli


@pytest.mark.asyncio
async def test_without_a_question_the_cli_goes_straight_to_the_prompt(cli_run, capsys):
    seen, start = cli_run
    await start(["Hello, Waffi."], "--fixtures", lines=["hi"])

    assert seen["prompts"] == ["> ", "> "]
    assert "Hello, Waffi." in capsys.readouterr().out


@pytest.mark.asyncio
async def test_with_a_question_the_cli_answers_it_then_prompts(cli_run, capsys):
    seen, start = cli_run
    await start(["Monday is free."], "--fixtures", "Is Monday free?")

    assert "Monday is free." in capsys.readouterr().out
    assert seen["prompts"] == ["> "]


@pytest.mark.asyncio
async def test_a_follow_up_is_answered_with_the_earlier_conversation(cli_run):
    seen, start = cli_run
    shown = []

    def second(messages):
        shown.extend(m.content for m in messages)
        return AIMessage(content="Yes, also free.")

    await start(["Monday is free.", second], "--fixtures", "Is Monday free?", lines=["And Tuesday?"])

    assert "Is Monday free?" in shown and "Monday is free." in shown and "And Tuesday?" in shown


@pytest.mark.parametrize("end", ["exit", "quit", " QUIT "])
@pytest.mark.asyncio
async def test_an_empty_line_does_nothing_and_exit_or_quit_ends_the_session(cli_run, capsys, end):
    seen, start = cli_run
    await start(["Hello."], "--fixtures", lines=["", "   ", "hi", end, "never asked"])

    assert seen["prompts"] == ["> "] * 4
    assert capsys.readouterr().out.count("Hello.") == 1


@pytest.mark.asyncio
async def test_the_conversation_id_is_printed_at_start_and_at_exit(cli_run, capsys):
    seen, start = cli_run
    await start(["Hello."], "--fixtures", "hi")

    lines = [line for line in capsys.readouterr().out.splitlines() if line.startswith("Conversation ")]
    thread_id = lines[0].removeprefix("Conversation ")
    assert lines == [f"Conversation {thread_id}"] * 2
    assert uuid.UUID(thread_id)


@pytest.mark.asyncio
async def test_debug_shows_after_each_turn_only_what_that_turn_added(cli_run, capsys):
    seen, start = cli_run
    await start(["Monday is free.", "Tuesday too."], "--fixtures", "--debug", "Is Monday free?",
                lines=["And Tuesday?"])

    out = capsys.readouterr().out
    first, second = out.split("DEBUG: MESSAGE TRAJECTORY")[1:]
    assert "Is Monday free?" in first and "And Tuesday?" not in first
    assert "And Tuesday?" in second and "Is Monday free?" not in second


def _usage(input_tokens):
    return {"input_tokens": input_tokens, "output_tokens": 0, "total_tokens": input_tokens}


@pytest.mark.asyncio
async def test_at_exit_one_run_log_entry_covers_the_whole_conversation(cli_run, monkeypatch):
    seen, start = cli_run
    monkeypatch.setattr(cli.settings, "model_name", "anthropic:claude-sonnet-5-5")
    await start(
        [
            AIMessage(content="Monday is free.", usage_metadata=_usage(1_000_000)),
            mail("ann", "c1"),
            AIMessage(content="Mailed Ann.", usage_metadata=_usage(1_000_000)),
        ],
        "Is Monday free?",
        lines=["Mail Ann about it.", "approve"],
    )

    [run] = seen["logged"]
    assert run.user_input == "Is Monday free?\nMail Ann about it."
    assert run.final_output == "Monday is free.\nMailed Ann."
    assert run.tools_called == ["send_mail"]
    assert run.token_usage["total"] == 2_000_000
    assert run.cost_usd == pytest.approx(4.0)  # $2.00 per 1M input tokens
    assert run.outcome == "completed"


@pytest.mark.asyncio
async def test_a_fixture_world_conversation_writes_no_run_log(cli_run):
    seen, start = cli_run
    await start(["Hello.", "Hello again."], "--fixtures", "hi", lines=["again"])

    assert seen["logged"] == []


@pytest.mark.parametrize("answer", ["approve", " APPROVE "])
@pytest.mark.asyncio
async def test_approve_at_the_approval_prompt_runs_the_write_action(cli_run, capsys, answer):
    seen, start = cli_run
    await start([mail("ann", "c1"), "Mailed Ann."], "--fixtures", lines=["Mail Ann.", answer])

    assert seen["ran"] == ["ann"]
    assert "Mailed Ann." in capsys.readouterr().out
    assert seen["prompts"] == ["> ", "Your decision: ", "> "]


@pytest.mark.asyncio
async def test_reject_at_the_approval_prompt_runs_nothing(cli_run):
    seen, start = cli_run
    await start([mail("ann", "c1"), "Not mailed."], "--fixtures", lines=["Mail Ann.", "Reject"])

    assert seen["ran"] == []


@pytest.mark.asyncio
async def test_a_follow_up_at_the_approval_prompt_rejects_and_is_answered(cli_run, capsys):
    seen, start = cli_run
    await start(
        [mail("ann", "c1"), "Not mailed.", "Monday is free."],
        "--fixtures",
        lines=["Mail Ann.", "Actually, is Monday free?"],
    )

    assert seen["ran"] == []
    assert "Monday is free." in capsys.readouterr().out
    assert seen["prompts"] == ["> ", "Your decision: ", "> "]


@pytest.mark.asyncio
async def test_a_single_unrecognised_word_asks_again_and_rejects_nothing(cli_run, capsys):
    seen, start = cli_run
    await start([mail("ann", "c1"), "Mailed Ann."], "--fixtures", lines=["Mail Ann.", "aprove", "approve"])

    assert seen["ran"] == ["ann"]
    assert seen["prompts"] == ["> ", "Your decision: ", "Your decision: ", "> "]
    assert "Please type 'approve' or 'reject'" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_the_approval_prompt_says_a_follow_up_question_rejects(cli_run, capsys):
    seen, start = cli_run
    await start([mail("ann", "c1"), "Mailed Ann."], "--fixtures", lines=["Mail Ann.", "approve"])

    assert "follow-up question: it rejects" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_a_moved_on_approval_is_logged_as_rejected(cli_run):
    seen, start = cli_run
    await start([mail("ann", "c1"), "Not mailed.", "Monday is free."], "Mail Ann.", lines=["Is Monday free?"])

    [run] = seen["logged"]
    assert run.outcome == "rejected"
