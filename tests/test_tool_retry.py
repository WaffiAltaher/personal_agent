import logging

import httplib2
import pytest
from googleapiclient.errors import HttpError
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command, interrupt

import agent.graph as graph_module
from agent.graph import build_graph
from agent.tools.classification import read_tool, write_action


@pytest.fixture(autouse=True)
def no_backoff_wait(monkeypatch):
    """Keep the retry semantics but skip the real sleeps."""
    monkeypatch.setattr(
        graph_module,
        "TOOL_RETRY_POLICY",
        graph_module.TOOL_RETRY_POLICY._replace(initial_interval=0.0, jitter=False),
    )


@pytest.fixture
def run_with_tool_calls(scripted_model):
    async def run(tools, tool_calls):
        """Drive one tool round: LLM requests tool_calls, then gives a final answer."""
        responses = [AIMessage(content="", tool_calls=tool_calls), AIMessage(content="done")]
        graph = build_graph(tools=tools, model=scripted_model(responses))
        return await graph.ainvoke({"messages": [HumanMessage(content="go")]})
    return run


def tool_messages(result):
    return {m.tool_call_id: m for m in result["messages"] if isinstance(m, ToolMessage)}


@pytest.mark.asyncio
async def test_transient_error_is_retried_until_success(run_with_tool_calls):
    attempts = {"n": 0}

    @read_tool
    @tool("flaky_read")
    async def flaky_read() -> str:
        """Fails twice with a network blip, then succeeds."""
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise ConnectionError("blip")
        return "file contents"

    result = await run_with_tool_calls([flaky_read], [{"id": "c1", "name": "flaky_read", "args": {}}])

    assert attempts["n"] == 3
    assert tool_messages(result)["c1"].content == "file contents"


@pytest.mark.asyncio
async def test_permanent_error_is_not_retried(run_with_tool_calls):
    attempts = {"n": 0}

    @read_tool
    @tool("forbidden_read")
    async def forbidden_read() -> str:
        """Always fails with 403 Forbidden."""
        attempts["n"] += 1
        raise HttpError(httplib2.Response({"status": "403"}), b"insufficient scope")

    result = await run_with_tool_calls([forbidden_read], [{"id": "c1", "name": "forbidden_read", "args": {}}])

    assert attempts["n"] == 1
    msg = tool_messages(result)["c1"]
    assert msg.status == "error"
    assert "permanent" in msg.content


@pytest.mark.asyncio
async def test_parallel_success_survives_a_failing_sibling(run_with_tool_calls):
    calls = {"down": 0, "note": 0}

    @read_tool
    @tool("down_read")
    async def down_read() -> str:
        """Always fails with a network error."""
        calls["down"] += 1
        raise ConnectionError("service down")

    @read_tool  # read-classified so the batch runs without an approval pause
    @tool("write_note")
    async def write_note() -> str:
        """Succeeds; has a side effect."""
        calls["note"] += 1
        return "note saved"

    result = await run_with_tool_calls(
        [down_read, write_note],
        [{"id": "c1", "name": "down_read", "args": {}}, {"id": "c2", "name": "write_note", "args": {}}],
    )

    msgs = tool_messages(result)
    assert calls["down"] == graph_module.TOOL_RETRY_POLICY.max_attempts
    assert calls["note"] == 1                      # side effect happened exactly once
    assert msgs["c2"].content == "note saved"      # and the model is told the truth
    assert msgs["c1"].status == "error"
    assert "transient" in msgs["c1"].content


@pytest.mark.asyncio
async def test_interrupt_inside_a_tool_pauses_the_graph(scripted_model):
    """interrupt() raises GraphInterrupt; neither retry_tool_call nor the fallback may swallow it."""
    @read_tool
    @tool("ask_human")
    async def ask_human() -> str:
        """Pauses for human input."""
        return interrupt("ok?")

    responses = [AIMessage(content="", tool_calls=[{"id": "c1", "name": "ask_human", "args": {}}]),
                 AIMessage(content="done")]
    graph = build_graph(checkpointer=InMemorySaver(), tools=[ask_human], model=scripted_model(responses))
    result = await graph.ainvoke({"messages": [HumanMessage(content="go")]},
                                 config={"configurable": {"thread_id": "t1"}})

    assert "__interrupt__" in result
    assert not tool_messages(result)


@pytest.mark.asyncio
async def test_permanent_error_is_logged_with_traceback(caplog, run_with_tool_calls):
    @read_tool
    @tool("buggy_read")
    async def buggy_read() -> str:
        """Has a code bug."""
        raise TypeError("bad operand")

    with caplog.at_level(logging.WARNING, logger="agent.graph"):
        await run_with_tool_calls([buggy_read], [{"id": "c1", "name": "buggy_read", "args": {}}])

    records = [r for r in caplog.records if r.getMessage() == "Tool call failed"]
    assert records and records[0].exc_info is not None
    assert records[0].exc_info[0] is TypeError


@pytest.mark.asyncio
async def test_write_tool_transient_error_is_not_retried(scripted_model):
    calls = {"n": 0}

    @write_action
    @tool("create_draft_email")
    async def create_draft_email() -> str:
        """Saves a draft; fails with a network blip."""
        calls["n"] += 1
        raise ConnectionError("blip")

    responses = [AIMessage(content="", tool_calls=[{"id": "c1", "name": "create_draft_email", "args": {}}]),
                 AIMessage(content="done")]
    graph = build_graph(checkpointer=InMemorySaver(), tools=[create_draft_email], model=scripted_model(responses))
    config = {"configurable": {"thread_id": "t1"}}
    await graph.ainvoke({"messages": [HumanMessage(content="go")]}, config=config)
    result = await graph.ainvoke(Command(resume="approve"), config=config)

    msg = tool_messages(result)["c1"]
    assert calls["n"] == 1
    assert msg.status == "error"
    assert "not retried" in msg.content
