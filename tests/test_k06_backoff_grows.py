from types import SimpleNamespace
import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool
import agent.graph as graph_module
from agent.graph import build_graph
from agent.tools.classification import read_tool


@pytest.mark.asyncio
async def test_backoff_doubles_between_attempts(scripted_model, monkeypatch):
    waits = []

    async def fake_sleep(seconds):
        waits.append(seconds)

    monkeypatch.setattr(graph_module, "asyncio", SimpleNamespace(sleep=fake_sleep))
    monkeypatch.setattr(graph_module, "TOOL_RETRY_POLICY", graph_module.TOOL_RETRY_POLICY._replace(jitter=False))

    @read_tool
    @tool("down_read")
    async def down_read() -> str:
        """Always fails with a network error."""
        raise ConnectionError("down")

    graph = build_graph(tools=[down_read], model=scripted_model(
        [AIMessage(content="", tool_calls=[{"id": "c1", "name": "down_read", "args": {}}]), AIMessage(content="done")]))
    await graph.ainvoke({"messages": [HumanMessage(content="go")]})

    assert waits == [1.0, 2.0]
