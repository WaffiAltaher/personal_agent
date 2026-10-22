import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool
import agent.graph as graph_module
from agent.graph import build_graph
from agent.tools.classification import read_tool


@pytest.mark.asyncio
async def test_two_failures_in_one_batch_are_both_recorded(scripted_model, monkeypatch):
    monkeypatch.setattr(graph_module, "TOOL_RETRY_POLICY",
                        graph_module.TOOL_RETRY_POLICY._replace(initial_interval=0.0, jitter=False))

    @read_tool
    @tool("broken_a")
    async def broken_a() -> str:
        """Always fails."""
        raise ValueError("a is broken")

    @read_tool
    @tool("broken_b")
    async def broken_b() -> str:
        """Always fails."""
        raise ValueError("b is broken")

    calls = [{"id": "a", "name": "broken_a", "args": {}}, {"id": "b", "name": "broken_b", "args": {}}]
    graph = build_graph(tools=[broken_a, broken_b],
                        model=scripted_model([AIMessage(content="", tool_calls=calls), AIMessage(content="done")]))
    result = await graph.ainvoke({"messages": [HumanMessage(content="go")]})

    assert sorted(e["tool_call_id"] for e in result["errors"]) == ["a", "b"]
