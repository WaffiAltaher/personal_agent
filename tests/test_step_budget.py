"""Ticket 20: model-call step budget across approvals."""

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver

from agent.config import settings
from agent.conversation import run_conversation
from agent.graph import STEP_LIMIT_ANSWER, build_graph, log_run_to_memory
from agent.memory.episodic import EpisodicMemory, RunRecord
from agent.tools.classification import read_tool, write_action


@pytest.mark.asyncio
async def test_tool_loop_stops_after_configured_model_calls(scripted_model, monkeypatch):
    monkeypatch.setattr(settings, "max_iterations", 4)
    calls = []

    @read_tool
    @tool
    async def ping() -> str:
        """Return pong."""
        return "pong"

    def forever(_messages):
        calls.append(1)
        return AIMessage(content="", tool_calls=[{"id": f"p{len(calls)}", "name": "ping", "args": {}}])

    tools = [ping]
    graph = build_graph(
        checkpointer=InMemorySaver(),
        tools=tools,
        model=scripted_model([forever] * 50),
    )
    config = {"configurable": {"thread_id": "t-limit"}}
    result = await run_conversation(graph, config, tools=tools, user_message="go")

    assert len(calls) == 4
    assert result["messages"][-1].content == STEP_LIMIT_ANSWER


@pytest.mark.asyncio
async def test_approving_three_times_does_not_reset_model_call_count(scripted_model, monkeypatch):
    monkeypatch.setattr(settings, "max_iterations", 3)

    @write_action
    @tool
    async def send_mail() -> str:
        """Send mail."""
        return "sent"

    calls = []

    def propose_write(_messages):
        calls.append(1)
        return AIMessage(
            content="",
            tool_calls=[{"id": f"w{len(calls)}", "name": "send_mail", "args": {}}],
        )

    tools = [send_mail]
    graph = build_graph(
        checkpointer=InMemorySaver(),
        tools=tools,
        model=scripted_model([propose_write] * 20),
    )
    config = {"configurable": {"thread_id": "t-approvals"}}
    result = await run_conversation(graph, config, tools=tools, user_message="go")
    while "__interrupt__" in result:
        result = await run_conversation(graph, config, tools=tools, resume_decision="approve")

    assert len(calls) == 3
    assert result["messages"][-1].content == STEP_LIMIT_ANSWER


@pytest.mark.asyncio
async def test_new_user_message_resets_model_call_count(scripted_model, monkeypatch):
    monkeypatch.setattr(settings, "max_iterations", 2)
    calls = []

    @read_tool
    @tool
    async def ping() -> str:
        """Return pong."""
        return "pong"

    def forever(_messages):
        calls.append(1)
        return AIMessage(content="", tool_calls=[{"id": f"p{len(calls)}", "name": "ping", "args": {}}])

    tools = [ping]
    graph = build_graph(
        checkpointer=InMemorySaver(),
        tools=tools,
        model=scripted_model([forever] * 50),
    )
    config = {"configurable": {"thread_id": "t-reset"}}
    await run_conversation(graph, config, tools=tools, user_message="first")
    assert len(calls) == 2

    result = await run_conversation(graph, config, tools=tools, user_message="second question")
    assert len(calls) == 4
    assert result["messages"][-1].content == STEP_LIMIT_ANSWER


def test_run_log_records_step_limit_outcome(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "sqlite_path", str(tmp_path / "episodic.db"))
    episodic = EpisodicMemory()
    written: list[RunRecord] = []

    def capture(_self, run: RunRecord) -> str:
        written.append(run)
        return episodic.log_run(run)

    monkeypatch.setattr(
        "agent.graph.get_episodic_memory",
        lambda: type("M", (), {"log_run": capture})(),
    )
    result = {
        "messages": [
            HumanMessage(content="loop"),
            AIMessage(content=STEP_LIMIT_ANSWER),
        ]
    }
    log_run_to_memory(result, "loop")

    assert len(written) == 1
    assert written[0].outcome == "step limit"
