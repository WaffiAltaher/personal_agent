"""
The Approval card and Stop from the web (ticket web-interface/05).

Same served app and stand-in model as test_web_turns: real HTTP and Server-Sent Events on the
test's own loop, a real checkpoint file, scripted replies (ADR-011: no live model).
"""

import asyncio

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import tool
from web.test_web_turns import TOOLS, Wait, ai, names, serve  # noqa: F401

from agent.conversation import INTERRUPTED_BY_OWNER, MOVED_ON_REJECTION
from agent.tools.classification import read_tool
from agent.web.logins import Integration, Logins
from agent.web.turns import apply_event

pytestmark = pytest.mark.asyncio


async def parked(web, question):
    """Start a Conversation and wait until it parks at an Approval: (thread_id, pending)."""
    thread_id = await web.start(question)
    async with web.events(thread_id) as stream:
        events = await stream.settled()
    state = (await web.client.get(f"/api/conversations/{thread_id}")).json()
    assert state["pending"], events
    return thread_id, state["pending"]


async def decide(web, thread_id, interrupt_id, decision):
    return await web.client.post(f"/api/conversations/{thread_id}/approval",
                                 json={"interrupt_id": interrupt_id, "decision": decision},
                                 headers={"Origin": web.origin})


async def stop(web, thread_id):
    return await web.client.post(f"/api/conversations/{thread_id}/stop", headers={"Origin": web.origin})


async def messages(web, thread_id):
    return (await web.app.state.graph.aget_state({"configurable": {"thread_id": thread_id}})).values["messages"]


async def test_approve_runs_the_write_action_and_the_turn_continues(serve):
    web = await serve({"Mail Ann": [ai("", ("w1", "send_mail", {"to": "ann"})), ai("Mail sent.")]})
    thread_id, pending = await parked(web, "Mail Ann")

    async with web.events(thread_id) as stream:
        name, state = await stream.next()
        assert state["status"] == "awaiting_approval"
        assert (await decide(web, thread_id, pending["interrupt_id"], "approve")).status_code == 202
        events = await stream.until("turn_ended")

    assert names(events) == ["approval_decided", "step_finished", "answer", "turn_ended"]
    assert events[0][1] == {"interrupt_id": pending["interrupt_id"], "decision": "approve"}
    assert events[1][1]["step"]["result"] == "sent"
    assert events[3][1] == {"status": "idle", "outcome": "answered", "message": None}
    transcript = (await web.client.get(f"/api/conversations/{thread_id}")).json()
    assert transcript["pending"] is None
    assert transcript["turns"][0]["answer"] == "Mail sent."


async def test_reject_injects_the_rejection_and_the_agent_acknowledges(serve):
    web = await serve({"Mail Ann": [ai("", ("w1", "send_mail", {"to": "ann"})), ai("Understood, not sent.")]})
    thread_id, pending = await parked(web, "Mail Ann")

    async with web.events(thread_id) as stream:
        await stream.next()
        assert (await decide(web, thread_id, pending["interrupt_id"], "reject")).status_code == 202
        events = await stream.until("turn_ended")

    assert names(events) == ["approval_decided", "step_finished", "answer", "turn_ended"]
    step = events[1][1]["step"]
    assert step["error"] is True and "rejected" in step["result"]
    assert events[2][1] == {"text": "Understood, not sent."}


async def test_a_turn_with_several_interrupts_shows_a_card_for_each_in_turn(serve):
    web = await serve({"Mail both": [
        ai("", ("w1", "send_mail", {"to": "ann"})),
        ai("", ("w2", "send_mail", {"to": "bob"})),
        ai("Both sent."),
    ]})
    thread_id, first = await parked(web, "Mail both")

    async with web.events(thread_id) as stream:
        await stream.next()
        await decide(web, thread_id, first["interrupt_id"], "approve")
        events = await stream.until("turn_ended")
        second = next(data["pending"] for name, data in events if name == "approval_pending")
        assert events[-1][1]["status"] == "awaiting_approval"
        assert second["tool_call_ids"] == ["w2"] and second["interrupt_id"] != first["interrupt_id"]

        await decide(web, thread_id, second["interrupt_id"], "approve")
        events = await stream.until("turn_ended")

    assert ("answer", {"text": "Both sent."}) in events


async def test_a_stale_decision_is_refused_and_both_tabs_see_the_card_resolve(serve):
    web = await serve({"Mail Ann": [ai("", ("w1", "send_mail", {"to": "ann"})), ai("Sent.")]})
    thread_id, pending = await parked(web, "Mail Ann")

    assert (await decide(web, thread_id, "not-the-pending-one", "approve")).status_code == 409
    async with web.events(thread_id) as tab_a, web.events(thread_id) as tab_b:
        await tab_a.next()
        await tab_b.next()
        assert (await decide(web, thread_id, pending["interrupt_id"], "approve")).status_code == 202
        events_a = await tab_a.until("turn_ended")
        events_b = await tab_b.until("turn_ended")
        # The other tab answers the same card again: it is no longer pending.
        assert (await decide(web, thread_id, pending["interrupt_id"], "reject")).status_code == 409

    assert events_a == events_b
    assert events_b[0] == ("approval_decided", {"interrupt_id": pending["interrupt_id"], "decision": "approve"})


async def test_a_decision_is_refused_while_a_turn_runs_and_on_a_thread_with_no_approval(serve):
    gate = asyncio.Event()
    web = await serve({"slow": [Wait(gate, ai("Done."))]})
    thread_id = await web.start("slow")

    assert (await decide(web, thread_id, "any", "approve")).status_code == 409
    gate.set()
    async with web.events(thread_id) as stream:
        await stream.settled()
    assert (await decide(web, thread_id, "any", "approve")).status_code == 409
    assert (await decide(web, thread_id, "any", "maybe")).status_code == 422
    assert (await decide(web, "nope", "any", "approve")).status_code == 404


async def test_a_follow_up_while_an_approval_waits_rejects_it_and_is_answered_as_the_next_turn(serve):
    web = await serve({"Mail Ann": [
        ai("", ("w1", "send_mail", {"to": "ann"})),
        ai("Not sent."),             # acknowledges the rejection
        ai("Your notes are empty."),  # answers the Follow-up
    ]})
    thread_id, pending = await parked(web, "Mail Ann")

    async with web.events(thread_id) as stream:
        _, state = await stream.next()
        assert (await web.ask(thread_id, "Read my notes instead")).status_code == 202
        events = await stream.until("turn_ended")

    assert names(events) == ["approval_decided", "step_finished", "answer", "turn_started", "answer", "turn_ended"]
    assert events[0][1] == {"interrupt_id": pending["interrupt_id"], "decision": "reject"}
    step = events[1][1]["step"]
    assert (step["id"], step["error"]) == ("w1", True) and MOVED_ON_REJECTION in step["result"]
    # A tab that applied the events shows what a reload shows: the Write step resolved as rejected.
    live = state["transcript"]
    for name, data in events:
        apply_event(live, name, data)
    reloaded = (await web.client.get(f"/api/conversations/{thread_id}")).json()
    assert live == reloaded
    assert [t["answer"] for t in reloaded["turns"]] == ["Not sent.", "Your notes are empty."]


def slow_read(gate: asyncio.Event):
    """A read that runs until the test sets ``gate``."""
    @read_tool
    @tool("slow_read")
    async def slow_read(topic: str) -> str:
        """Reads slowly."""
        await gate.wait()
        return "late"
    return slow_read


async def test_stop_cancels_a_running_turn_and_closes_its_open_tool_calls(serve):
    web = await serve({"Read slowly": [ai("", ("s1", "slow_read", {"topic": "tax"})), ai("After the stop.")]},
                      tools=[slow_read(asyncio.Event()), *TOOLS])
    thread_id = await web.start("Read slowly")
    async with web.events(thread_id) as stream:
        await stream.until("step_started")
        assert (await stop(web, thread_id)).status_code == 202
        events = await stream.until("turn_ended")

        assert names(events) == ["step_finished", "turn_ended"]
        step = events[0][1]["step"]
        assert (step["id"], step["error"], step["result"]) == ("s1", True, INTERRUPTED_BY_OWNER)
        assert events[1][1] == {"status": "idle", "outcome": "cancelled", "message": "Interrupted."}
        # The thread ends on answered messages: every tool call has its result.
        thread = await messages(web, thread_id)
        calls = {c["id"] for m in thread if isinstance(m, AIMessage) for c in m.tool_calls}
        assert calls == {m.tool_call_id for m in thread if isinstance(m, ToolMessage)}
        [run] = web.memory.get_recent_runs(10)
        assert run.thread_id == thread_id

        assert (await web.ask(thread_id, "Again")).status_code == 202
        assert ("answer", {"text": "After the stop."}) in await stream.until("turn_ended")


async def test_stop_while_a_follow_up_abandons_the_approval_lands_where_a_reload_shows_it(serve):
    gate = asyncio.Event()
    web = await serve({"Mail Ann": [
        ai("", ("w1", "send_mail", {"to": "ann"})),
        Wait(gate, ai("Not sent.")),  # the acknowledgement the Stop cancels
    ]})
    thread_id, _ = await parked(web, "Mail Ann")

    async with web.events(thread_id) as stream:
        _, state = await stream.next()
        assert (await web.ask(thread_id, "Read my notes instead")).status_code == 202
        events = await stream.until("step_finished")  # the earlier turn's Write step, rejected
        assert (await stop(web, thread_id)).status_code == 202
        events += await stream.until("turn_ended")

    assert events[-1][1] == {"status": "idle", "outcome": "cancelled", "message": "Interrupted."}
    live = state["transcript"]
    for name, data in events:
        apply_event(live, name, data)
    reloaded = (await web.client.get(f"/api/conversations/{thread_id}")).json()
    assert live == reloaded
    # The Follow-up never reached the thread: the stop belongs to the turn it was ending.
    assert [(t["question"], t.get("stopped")) for t in reloaded["turns"]] == [("Mail Ann", "Interrupted.")]


async def test_stop_before_a_follow_ups_question_is_saved_shows_what_a_reload_shows(serve):
    hold, checking = asyncio.Event(), asyncio.Event()

    async def check():
        if hold.is_set():  # the Follow-up's turn waits on this login refresh until the Stop
            checking.set()
            await asyncio.Event().wait()
        return None

    web = await serve({"Hi": [ai("Hello.")]}, logins=Logins([Integration("Slow", "log in", check)], turn_wait_s=30))
    thread_id = await web.start("Hi")
    async with web.events(thread_id) as stream:
        await stream.settled()
    hold.set()

    async with web.events(thread_id) as stream:
        _, state = await stream.next()
        assert (await web.ask(thread_id, "And then?")).status_code == 202
        await checking.wait()
        assert (await stop(web, thread_id)).status_code == 202
        events = await stream.until("turn_ended")

    live = state["transcript"]
    for name, data in events:
        if name == "state":
            live = data["transcript"]
        else:
            apply_event(live, name, data)
    reloaded = (await web.client.get(f"/api/conversations/{thread_id}")).json()
    assert live == reloaded
    assert [(t["question"], t.get("stopped")) for t in reloaded["turns"]] == [("Hi", "Interrupted.")]


async def test_stop_is_refused_when_no_turn_runs(serve):
    web = await serve({"Hi": [ai("Hello.")]})
    thread_id = await web.start("Hi")
    async with web.events(thread_id) as stream:
        await stream.settled()

    assert (await stop(web, thread_id)).status_code == 409
    assert (await stop(web, "nope")).status_code == 404


async def test_the_run_log_entry_is_written_after_parked_approved_and_rejected_turns(serve):
    web = await serve({"Mail Ann": [
        ai("", ("w1", "send_mail", {"to": "ann"})), ai("Sent."),
        ai("", ("w2", "send_mail", {"to": "bob"})), ai("Not sent."),
    ]})
    thread_id, pending = await parked(web, "Mail Ann")
    [run] = web.memory.get_recent_runs(10)
    assert (run.thread_id, run.final_output) == (thread_id, "")

    async with web.events(thread_id) as stream:
        await stream.next()
        await decide(web, thread_id, pending["interrupt_id"], "approve")
        await stream.until("turn_ended")
        [run] = web.memory.get_recent_runs(10)
        assert run.final_output == "Sent."

        await web.ask(thread_id, "Mail Bob")
        events = await stream.until("turn_ended")
        pending = next(data["pending"] for name, data in events if name == "approval_pending")
        await decide(web, thread_id, pending["interrupt_id"], "reject")
        await stream.until("turn_ended")

    [run] = web.memory.get_recent_runs(10)
    assert (run.user_input, run.final_output) == ("Mail Ann\nMail Bob", "Sent.\nNot sent.")
