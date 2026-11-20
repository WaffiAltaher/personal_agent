"""The run log entry is written when each turn ends, not only at exit."""
import asyncio
import signal

import pytest
from _cli_harness import cli_run, mail  # noqa: F401
from langchain_core.messages import AIMessage

import agent.cli as cli
import agent.turn_rules as turn_rules
from agent.claude_code_model import ClaudeCodeError
from test_cli_ctrl_c import slow, slow_lookup


def _conversation_id(out):
    return next(line for line in out.splitlines() if line.startswith("Conversation ")).removeprefix("Conversation ")


@pytest.mark.asyncio
async def test_the_entry_exists_after_each_turn_and_covers_every_turn_so_far(cli_run, monkeypatch):
    seen, start = cli_run
    after_turn = []

    def snapshot(reply):
        def answer(messages):
            after_turn.append([(r.user_input, r.final_output) for r in seen["logged"]])
            return AIMessage(content=reply)
        return answer

    await start([snapshot("One."), snapshot("Two."), AIMessage(content="Three.")],
                "first?", lines=["second?", "third?"])

    # While turn 2 and 3 run, the entry from the turns before them is already stored.
    assert after_turn[0] == []
    assert after_turn[1] == [("first?", "One.")]
    # Three writes (one per turn) + the exit pass, still one entry for the thread.
    assert len(seen["writes"]) == 4
    [run] = seen["logged"]
    assert run.user_input == "first?\nsecond?\nthird?"
    assert run.final_output == "One.\nTwo.\nThree."


@pytest.mark.asyncio
async def test_a_turn_parked_at_an_approval_leaves_an_entry(cli_run):
    seen, start = cli_run
    await start([mail("ann@x.com", "c1")], "--fixtures", "Mail Ann.", lines=["", ])
    # fixtures: nothing written; the real-world case follows
    assert seen["writes"] == []

    await start([mail("ann@x.com", "c2")], "Mail Ann.")
    assert len(seen["writes"]) >= 2  # after the parked turn, and at exit
    assert seen["logged"][-1].user_input == "Mail Ann."


@pytest.mark.asyncio
async def test_a_failed_turn_leaves_an_error_a_later_turn_keeps_without_repeating_it(cli_run):
    seen, start = cli_run

    def stopped(messages):
        raise ClaudeCodeError("limit reached")

    states = []

    def answer(messages):
        states.append([(r.outcome, r.error_message) for r in seen["logged"]])
        return AIMessage(content="Fine.")

    await start([stopped, answer], "first?", lines=["again?"])

    assert states == [[("error", "ClaudeCodeError: limit reached")]]
    [run] = seen["logged"]
    assert run.error_message == "ClaudeCodeError: limit reached"
    assert run.user_input == "first?\nagain?"


@pytest.mark.asyncio
async def test_a_resumed_conversation_keeps_earlier_errors_after_its_next_turn(cli_run, capsys):
    seen, start = cli_run

    def stopped(messages):
        raise ClaudeCodeError("limit reached")

    await start([stopped], "first?")
    thread_id = _conversation_id(capsys.readouterr().out)

    await start([AIMessage(content="Fine.")], "--resume", thread_id, "again?")

    [run] = seen["logged"]
    assert run.error_message == "ClaudeCodeError: limit reached"
    assert run.user_input == "first?\nagain?"


@pytest.mark.asyncio
async def test_a_cancelled_turn_leaves_an_entry(cli_run):
    seen, start = cli_run
    seen["tools"].append(slow_lookup)
    states = []

    def answer(messages):
        states.append(len(seen["logged"]))
        return AIMessage(content="Back.")

    await start([slow("c1"), answer], "Look it up.", lines=["again?"])

    assert states == [1]  # the cancelled turn's entry was there before the next turn ran
    [run] = seen["logged"]
    assert run.user_input == "Look it up.\nagain?"


@pytest.mark.asyncio
async def test_the_helper_needs_only_the_checkpoint_path_and_thread_id(cli_run, capsys):
    seen, start = cli_run
    await start([AIMessage(content="Hi.")], "hello?")
    thread_id = _conversation_id(capsys.readouterr().out)
    seen["logged"].clear()
    seen["writes"].clear()

    from agent import graph
    await turn_rules.write_run_log(graph.CHECKPOINT_DB, thread_id)

    [run] = seen["writes"]
    assert run.user_input == "hello?" and run.final_output == "Hi."
