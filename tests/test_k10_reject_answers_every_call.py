import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from agent.graph import build_graph
from agent.tools.classification import read_tool, write_action


@pytest.mark.asyncio
async def test_rejecting_a_mixed_batch_answers_every_tool_call(scripted_model):
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
    graph = build_graph(checkpointer=InMemorySaver(), tools=[read_notes, send_mail], model=scripted_model(
        [AIMessage(content="", tool_calls=calls), AIMessage(content="Cancelled.")]))
    config = {"configurable": {"thread_id": "t"}}
    await graph.ainvoke({"messages": [HumanMessage(content="go")]}, config=config)
    result = await graph.ainvoke(Command(resume="reject"), config=config)

    answered = {m.tool_call_id for m in result["messages"] if isinstance(m, ToolMessage)}
    assert answered == {"r1", "w1"}   # a provider rejects a history with an unanswered tool call
    assert runs == ["read_notes"]  # reads still run; the write action never executes
