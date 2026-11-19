"""The driver's streaming form (web-interface/04): the same turn rules as run_conversation, with
each node's update yielded as it happens."""

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver

from agent.conversation import APPROVAL_ABANDONED, ConversationDriverError, run_conversation, stream_conversation
from agent.graph import build_graph
from agent.tools.classification import read_tool, write_action

pytestmark = pytest.mark.asyncio


@read_tool
@tool("read_notes")
async def read_notes() -> str:
    """Reads notes."""
    return "notes"


@write_action
@tool("send_mail")
async def send_mail() -> str:
    """Sends mail."""
    return "sent"


TOOLS = [read_notes, send_mail]
CONFIG = {"configurable": {"thread_id": "t1"}}


def ai(text, *calls):
    return AIMessage(content=text, tool_calls=[{"id": i, "name": n, "args": {}} for i, n in calls])


async def collect(graph, **kwargs):
    return [chunk async for chunk in stream_conversation(graph, CONFIG, tools=TOOLS, **kwargs)]


def messages_of(chunks):
    return [m for chunk in chunks for update in chunk.values() if isinstance(update, dict)
            for m in update.get("messages", [])]


async def test_a_turn_yields_the_tool_call_its_result_then_the_answer_in_order(scripted_model):
    graph = build_graph(InMemorySaver(), TOOLS, scripted_model([ai("", ("c1", "read_notes")), ai("Done.")]))

    chunks = await collect(graph, user_message="Read my notes")

    call, result, answer = [m for m in messages_of(chunks) if not m.type == "human"]
    assert call.tool_calls[0]["id"] == "c1"
    assert isinstance(result, ToolMessage) and result.content == "notes"
    assert answer.content == "Done."
    # The thread holds the same turn as run_conversation would have left.
    state = await graph.aget_state(CONFIG)
    assert state.values["messages"][-1].content == "Done."


async def test_a_turn_parked_at_an_approval_yields_the_interrupt(scripted_model):
    graph = build_graph(InMemorySaver(), TOOLS, scripted_model([ai("", ("w1", "send_mail"))]))

    chunks = await collect(graph, user_message="Mail Ann")

    (interrupts,) = [chunk["__interrupt__"] for chunk in chunks if "__interrupt__" in chunk]
    assert interrupts[0].value["tool_call_ids"] == ["w1"]


async def test_a_follow_up_rejects_the_pending_approval_as_in_run_conversation(scripted_model):
    graph = build_graph(InMemorySaver(), TOOLS, scripted_model([ai("", ("w1", "send_mail")), ai("Ok, not sent."),
                                                                ai("Hello.")]))
    await run_conversation(graph, CONFIG, tools=TOOLS, user_message="Mail Ann")

    await collect(graph, user_message="Never mind, say hello")

    messages = (await graph.aget_state(CONFIG)).values["messages"]
    rejected = next(m for m in messages if isinstance(m, ToolMessage) and m.tool_call_id == "w1")
    assert rejected.status == "error"
    assert messages[-1].content == "Hello."


async def test_a_follow_up_yields_the_abandonment_then_a_marker_then_its_own_turn(scripted_model):
    graph = build_graph(InMemorySaver(), TOOLS, scripted_model([ai("", ("w1", "send_mail")), ai("Ok, not sent."),
                                                                ai("Hello.")]))
    await run_conversation(graph, CONFIG, tools=TOOLS, user_message="Mail Ann")

    chunks = await collect(graph, user_message="Never mind, say hello")

    at = next(i for i, chunk in enumerate(chunks) if APPROVAL_ABANDONED in chunk)
    before, after = messages_of(chunks[:at]), messages_of(chunks[at + 1:])
    assert [(m.type, m.content if m.type == "ai" else m.tool_call_id) for m in before] == [
        ("tool", "w1"), ("ai", "Ok, not sent.")]
    assert [m.content for m in after] == ["Hello."]


async def test_a_resume_without_a_pending_approval_is_refused(scripted_model):
    graph = build_graph(InMemorySaver(), TOOLS, scripted_model([]))

    with pytest.raises(ConversationDriverError):
        await collect(graph, resume_decision="approve")
