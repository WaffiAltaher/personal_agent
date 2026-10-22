import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from agent.graph import build_graph
from agent.tools.classification import write_action


@pytest.mark.asyncio
@pytest.mark.parametrize("decision", ["yes", "Approve", ""])
async def test_anything_but_approve_is_a_rejection(scripted_model, decision):
    runs = []

    @write_action
    @tool("send_mail")
    async def send_mail() -> str:
        """Sends mail."""
        runs.append("send_mail")
        return "sent"

    graph = build_graph(checkpointer=InMemorySaver(), tools=[send_mail], model=scripted_model(
        [AIMessage(content="", tool_calls=[{"id": "w1", "name": "send_mail", "args": {}}]), AIMessage(content="ok")]))
    config = {"configurable": {"thread_id": "t"}}
    await graph.ainvoke({"messages": [HumanMessage(content="go")]}, config=config)
    result = await graph.ainvoke(Command(resume=decision), config=config)

    assert runs == []
    [rejection] = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert "rejected by the user" in rejection.content
