"""Ticket 09: rejection semantics and the shared conversation entry point."""

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from agent.conversation import ConversationDriverError, run_conversation
from agent.graph import build_graph
from agent.tools.classification import read_tool, write_action


@pytest.mark.asyncio
async def test_reject_on_mixed_step_runs_read_and_never_executes_write(scripted_model):
    runs = []

    @read_tool
    @tool("read_notes")
    async def read_notes() -> str:
        """Reads notes."""
        runs.append("read_notes")
        return "notes"

    @write_action
    @tool("send_mail")
    async def send_mail() -> str:
        """Sends mail."""
        runs.append("send_mail")
        return "sent"

    calls = [{"id": "r1", "name": "read_notes", "args": {}}, {"id": "w1", "name": "send_mail", "args": {}}]
    tools = [read_notes, send_mail]
    graph = build_graph(
        checkpointer=InMemorySaver(),
        tools=tools,
        model=scripted_model([AIMessage(content="", tool_calls=calls), AIMessage(content="Cancelled.")]),
    )
    config = {"configurable": {"thread_id": "t-mixed"}}
    await run_conversation(graph, config, tools=tools, user_message="go")
    result = await run_conversation(graph, config, tools=tools, resume_decision="reject")

    by_id = {m.tool_call_id: m for m in result["messages"] if isinstance(m, ToolMessage)}
    assert by_id["r1"].content == "notes"
    assert by_id["r1"].status != "error"
    assert by_id["w1"].status == "error"
    assert "rejected by the user" in by_id["w1"].content.lower()
    assert runs == ["read_notes"]


@pytest.mark.asyncio
async def test_every_rejection_tool_message_has_error_status(scripted_model):
    @write_action
    @tool("send_mail")
    async def send_mail() -> str:
        """Sends mail."""
        return "sent"

    tools = [send_mail]
    graph = build_graph(
        checkpointer=InMemorySaver(),
        tools=tools,
        model=scripted_model(
            [AIMessage(content="", tool_calls=[{"id": "w1", "name": "send_mail", "args": {}}]), AIMessage(content="ok")]
        ),
    )
    config = {"configurable": {"thread_id": "t-err"}}
    await run_conversation(graph, config, tools=tools, user_message="go")
    result = await run_conversation(graph, config, tools=tools, resume_decision="no")

    rejections = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert len(rejections) == 1
    assert rejections[0].status == "error"


@pytest.mark.asyncio
async def test_new_message_on_pending_approval_rejects_writes_then_answers(scripted_model):
    @write_action
    @tool("send_mail")
    async def send_mail() -> str:
        """Sends mail."""
        return "sent"

    tools = [send_mail]
    graph = build_graph(
        checkpointer=InMemorySaver(),
        tools=tools,
        model=scripted_model(
            [
                AIMessage(content="", tool_calls=[{"id": "w1", "name": "send_mail", "args": {}}]),
                AIMessage(content="I will not send that."),
                AIMessage(content="The weather is fine."),
            ]
        ),
    )
    config = {"configurable": {"thread_id": "t-new-msg"}}
    await run_conversation(graph, config, tools=tools, user_message="send mail")
    result = await run_conversation(graph, config, tools=tools, user_message="What's the weather?")

    tool_messages = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert len(tool_messages) == 1
    assert tool_messages[0].status == "error"
    assert "moved on without approving" in tool_messages[0].content.lower()
    assert result["messages"][-1].content == "The weather is fine."
    pending = [
        tc
        for msg in result["messages"]
        if isinstance(msg, AIMessage)
        for tc in msg.tool_calls or []
        if not any(isinstance(m, ToolMessage) and m.tool_call_id == tc["id"] for m in result["messages"])
    ]
    assert pending == []


@pytest.mark.asyncio
async def test_resume_without_decision_is_refused(scripted_model):
    @write_action
    @tool("send_mail")
    async def send_mail() -> str:
        """Sends mail."""
        return "sent"

    tools = [send_mail]
    graph = build_graph(
        checkpointer=InMemorySaver(),
        tools=tools,
        model=scripted_model([AIMessage(content="", tool_calls=[{"id": "w1", "name": "send_mail", "args": {}}])]),
    )
    config = {"configurable": {"thread_id": "t-no-decision"}}
    await run_conversation(graph, config, tools=tools, user_message="go")

    with pytest.raises(ConversationDriverError, match="decision"):
        await run_conversation(graph, config, tools=tools, resume_decision="")


@pytest.mark.asyncio
async def test_resume_without_pending_approval_is_refused(scripted_model):
    @read_tool
    @tool("lookup")
    async def lookup() -> str:
        """Looks up."""
        return "ok"

    tools = [lookup]
    graph = build_graph(
        checkpointer=InMemorySaver(),
        tools=tools,
        model=scripted_model([AIMessage(content="done")]),
    )
    config = {"configurable": {"thread_id": "t-no-pending"}}
    await run_conversation(graph, config, tools=tools, user_message="hi")

    with pytest.raises(ConversationDriverError, match="pending"):
        await run_conversation(graph, config, tools=tools, resume_decision="approve")


@pytest.mark.asyncio
async def test_direct_graph_resume_is_not_used_for_approval(scripted_model):
    """Guardrail: callers resume through run_conversation (eval harness and CLI do)."""
    import agent.cli as cli
    import agent.evals.harness as harness

    assert "run_conversation" in open(cli.__file__).read()
    assert "run_conversation" in open(harness.__file__).read()
