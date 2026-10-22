"""After rejecting a write, a crash running the remaining read still answers that read."""

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver

import agent.graph as graph_module
from agent.conversation import run_conversation
from agent.graph import build_graph
from agent.tools.classification import read_tool, write_action


@pytest.mark.asyncio
async def test_reject_write_then_read_crash_still_returns_error_for_read(scripted_model, monkeypatch):
    monkeypatch.setattr(
        graph_module,
        "TOOL_RETRY_POLICY",
        graph_module.TOOL_RETRY_POLICY._replace(initial_interval=0.0, jitter=False),
    )

    @write_action
    @tool("send_mail")
    async def send_mail() -> str:
        """Send mail."""
        return "sent"

    @read_tool
    @tool("lookup")
    async def lookup(q: str) -> str:
        """Lookup."""
        return q

    tools = [send_mail, lookup]

    real_ainvoke = graph_module.ToolNode.ainvoke

    async def crashing_ainvoke(self, state):
        raise RuntimeError("read layer crashed")

    monkeypatch.setattr(graph_module.ToolNode, "ainvoke", crashing_ainvoke)
    graph = build_graph(
        checkpointer=InMemorySaver(),
        tools=tools,
        model=scripted_model(
            [
                AIMessage(
                    content="",
                    tool_calls=[
                        {"id": "w1", "name": "send_mail", "args": {}},
                        {"id": "r1", "name": "lookup", "args": {"q": "x"}},
                    ],
                ),
                AIMessage(content="Could not complete the lookup."),
            ]
        ),
    )
    config = {"configurable": {"thread_id": "t-reject-read-crash"}}
    result = await run_conversation(graph, config, tools=tools, user_message="go")
    result = await run_conversation(graph, config, tools=tools, resume_decision="reject")

    read_messages = [m for m in result["messages"] if isinstance(m, ToolMessage) and m.tool_call_id == "r1"]
    assert len(read_messages) == 1
    assert read_messages[0].status == "error"
    assert "crashed" in read_messages[0].content.lower() or "RuntimeError" in read_messages[0].content
