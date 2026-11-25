"""A Write action whose arguments can't be right is answered with an error before the owner is asked.

On 2026-11-25 the agent proposed ms365_save_attachment with the attachment's ID as message_id too;
the owner approved, Graph refused, and the corrected call needed a second Approval.
"""

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver

from agent.graph import build_graph
from agent.tools.classification import pre_approval_check, with_pre_approval_check, write_action
from agent.tools.ms365_attachments import build_save_attachment


def _save_tool(runs):
    def same_ids(args: dict) -> str | None:
        return "Error: same ids." if args.get("a") == args.get("b") else None

    @tool("save")
    async def save(a: str, b: str) -> str:
        """Saves."""
        runs.append((a, b))
        return "saved"

    return with_pre_approval_check(write_action(save), same_ids)


@pytest.mark.asyncio
async def test_a_failing_check_answers_the_call_without_asking_the_owner(scripted_model):
    runs = []
    tools = [_save_tool(runs)]
    graph = build_graph(
        checkpointer=InMemorySaver(),
        tools=tools,
        model=scripted_model([
            AIMessage(content="", tool_calls=[{"id": "w1", "name": "save", "args": {"a": "x", "b": "x"}}]),
            AIMessage(content="I'll fix the ids."),
        ]),
    )
    result = await graph.ainvoke({"messages": [HumanMessage("save it")]}, {"configurable": {"thread_id": "t1"}})

    assert "__interrupt__" not in result
    answer = next(m for m in result["messages"] if isinstance(m, ToolMessage))
    assert answer.tool_call_id == "w1"
    assert answer.status == "error"
    assert "same ids" in answer.content
    assert "not asked" in answer.content.lower()
    assert runs == []


@pytest.mark.asyncio
async def test_a_passing_check_still_asks_the_owner(scripted_model):
    runs = []
    tools = [_save_tool(runs)]
    graph = build_graph(
        checkpointer=InMemorySaver(),
        tools=tools,
        model=scripted_model([
            AIMessage(content="", tool_calls=[{"id": "w1", "name": "save", "args": {"a": "x", "b": "y"}}]),
        ]),
    )
    result = await graph.ainvoke({"messages": [HumanMessage("save it")]}, {"configurable": {"thread_id": "t2"}})

    assert result["__interrupt__"][0].value["tool_call_ids"] == ["w1"]
    assert runs == []


@pytest.mark.asyncio
async def test_only_the_calls_that_pass_are_put_to_the_owner(scripted_model):
    runs = []

    @write_action
    @tool("send_mail")
    async def send_mail() -> str:
        """Sends mail."""
        return "sent"

    tools = [_save_tool(runs), send_mail]
    graph = build_graph(
        checkpointer=InMemorySaver(),
        tools=tools,
        model=scripted_model([
            AIMessage(content="", tool_calls=[
                {"id": "w1", "name": "save", "args": {"a": "x", "b": "x"}},
                {"id": "w2", "name": "send_mail", "args": {}},
            ]),
            AIMessage(content="done"),
        ]),
    )
    config = {"configurable": {"thread_id": "t3"}}
    first = await graph.ainvoke({"messages": [HumanMessage("go")]}, config)
    assert first["__interrupt__"][0].value["tool_call_ids"] == ["w2"]

    from langgraph.types import Command
    result = await graph.ainvoke(Command(resume="approve"), config)
    by_id = {m.tool_call_id: m for m in result["messages"] if isinstance(m, ToolMessage)}
    assert by_id["w1"].status == "error"
    assert by_id["w2"].content == "sent"
    assert runs == []


def test_the_outlook_save_refuses_the_attachment_id_as_message_id():
    check = pre_approval_check(build_save_attachment("ms365_save_attachment", {}))
    assert check is not None
    refused = check({"message_id": "AAMk-ATT", "attachment_id": "AAMk-ATT", "file_name": "a.pdf"})
    assert refused and "message_id" in refused
    assert check({"message_id": "AAMk-MSG", "attachment_id": "AAMk-ATT", "file_name": "a.pdf"}) is None


@pytest.mark.asyncio
async def test_a_refused_call_keeps_its_error_when_the_owner_rejects_the_rest(scripted_model):
    runs = []

    @write_action
    @tool("send_mail")
    async def send_mail() -> str:
        """Sends mail."""
        return "sent"

    tools = [_save_tool(runs), send_mail]
    graph = build_graph(
        checkpointer=InMemorySaver(),
        tools=tools,
        model=scripted_model([
            AIMessage(content="", tool_calls=[
                {"id": "w1", "name": "save", "args": {"a": "x", "b": "x"}},
                {"id": "w2", "name": "send_mail", "args": {}},
            ]),
            AIMessage(content="ok"),
        ]),
    )
    config = {"configurable": {"thread_id": "t4"}}
    await graph.ainvoke({"messages": [HumanMessage("go")]}, config)

    from langgraph.types import Command
    result = await graph.ainvoke(Command(resume="reject"), config)
    by_id = {m.tool_call_id: m for m in result["messages"] if isinstance(m, ToolMessage)}
    assert "same ids" in by_id["w1"].content
    assert "rejected by the user" in by_id["w2"].content.lower()
    assert runs == []
