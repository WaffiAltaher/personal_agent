import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
import agent.graph as graph_module
from agent.graph import build_graph
from agent.tools.classification import read_tool


@pytest.mark.asyncio
async def test_a_crash_outside_the_tool_still_answers_every_tool_call(scripted_model, monkeypatch):
    """Simulate a bug below the fallback (in the retry wrapper itself): the run must not crash."""
    async def buggy_wrapper(request, execute):
        raise RuntimeError("bug in the retry wrapper")

    monkeypatch.setattr(graph_module, "retry_tool_call", buggy_wrapper)

    @read_tool
    @tool("read_a")
    async def read_a() -> str:
        """Reads a."""
        return "a"

    calls = [{"id": "c1", "name": "read_a", "args": {}}, {"id": "c2", "name": "read_a", "args": {}}]
    graph = build_graph(tools=[read_a], model=scripted_model(
        [AIMessage(content="", tool_calls=calls), AIMessage(content="Sorry, that tool is unavailable.")]))
    result = await graph.ainvoke({"messages": [HumanMessage(content="go")]})

    answered = {m.tool_call_id for m in result["messages"] if isinstance(m, ToolMessage)}
    assert answered == {"c1", "c2"}
    assert [e["exception_type"] for e in result["errors"]] == ["RuntimeError", "RuntimeError"]
    assert result["messages"][-1].content == "Sorry, that tool is unavailable."
