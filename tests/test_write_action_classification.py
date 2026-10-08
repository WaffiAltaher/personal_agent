"""
tests/test_write_action_classification.py

Fail-closed Write-action classification, exercised through the graph (seam A):
a tool is read only if it was classified as read when tools were loaded.
Anything else is a Write action: it pauses for approval and is never retried.
"""

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

import agent.graph as graph_module
from agent.graph import build_graph
from agent.tools import LOCAL_TOOLS
from agent.tools.classification import classify_mcp_tools, is_read


@pytest.fixture(autouse=True)
def no_backoff_wait(monkeypatch):
    """Keep the retry semantics but skip the real sleeps."""
    monkeypatch.setattr(
        graph_module,
        "TOOL_RETRY_POLICY",
        graph_module.TOOL_RETRY_POLICY._replace(initial_interval=0.0, jitter=False),
    )


@pytest.fixture
def start_run(scripted_model):
    async def start(tools, tool_calls, thread_id="t1"):
        """LLM requests tool_calls, then gives a final answer. Returns (graph, config, result)."""
        responses = [AIMessage(content="", tool_calls=tool_calls), AIMessage(content="done")]
        graph = build_graph(checkpointer=InMemorySaver(), tools=tools, model=scripted_model(responses))
        config = {"configurable": {"thread_id": thread_id}}
        result = await graph.ainvoke({"messages": [HumanMessage(content="go")]}, config=config)
        return graph, config, result
    return start


def tool_messages(result):
    return {m.tool_call_id: m for m in result["messages"] if isinstance(m, ToolMessage)}


@pytest.mark.asyncio
async def test_unclassified_tool_pauses_for_approval_and_is_not_retried(start_run):
    attempts = {"n": 0}

    @tool("mystery_tool")
    async def mystery_tool() -> str:
        """A tool nobody classified; fails with a transient network error."""
        attempts["n"] += 1
        raise ConnectionError("blip")

    graph, config, result = await start_run([mystery_tool], [{"id": "c1", "name": "mystery_tool", "args": {}}])

    assert "__interrupt__" in result
    assert "mystery_tool" in result["__interrupt__"][0].value["actions"]
    assert attempts["n"] == 0  # nothing ran before approval

    result = await graph.ainvoke(Command(resume="approve"), config=config)

    assert attempts["n"] == 1
    msg = tool_messages(result)["c1"]
    assert msg.status == "error"
    assert "not retried" in msg.content


@pytest.mark.asyncio
async def test_tool_name_that_is_not_bound_pauses_for_approval(start_run):
    _, _, result = await start_run(LOCAL_TOOLS, [{"id": "c1", "name": "ms365_send-mail", "args": {}}])

    assert "__interrupt__" in result
    assert "ms365_send-mail" in result["__interrupt__"][0].value["actions"]


def stand_in(real_tool):
    """A harmless tool with the real tool's name and classification, so the graph can run it offline."""
    @tool(real_tool.name)
    async def stub() -> str:
        """Stand-in."""
        return "ok"
    stub.metadata = real_tool.metadata
    return stub


async def pauses_for_approval(start_run, bound_tool) -> bool:
    _, _, result = await start_run(
        [stand_in(bound_tool)], [{"id": "c1", "name": bound_tool.name, "args": {}}], thread_id=bound_tool.name
    )
    return "__interrupt__" in result


@pytest.mark.asyncio
async def test_google_sources_gmail_draft_is_a_write_action_and_reads_are_read(start_run):
    by_name = {t.name: t for t in LOCAL_TOOLS}

    assert await pauses_for_approval(start_run, by_name["create_draft_email"])
    for name in ("search_gmail", "get_gmail_message", "list_calendar_events", "get_calendar_event"):
        assert not await pauses_for_approval(start_run, by_name[name]), name


def test_every_local_tool_declares_its_classification():
    undeclared = [t.name for t in LOCAL_TOOLS if (t.metadata or {}).get("action_class") not in ("read", "write")]
    assert undeclared == []


def mcp_tool(name, annotations=None):
    """What langchain-mcp-adapters produces: MCP annotations land in the tool's metadata."""
    @tool(name)
    async def stub() -> str:
        """MCP stand-in."""
        return "ok"
    stub.metadata = annotations
    return stub


@pytest.mark.asyncio
async def test_mcp_tool_is_read_only_via_allowlist_only_never_its_annotation(start_run):
    classified = classify_mcp_tools(
        [
            mcp_tool("srv_list-mail", {"readOnlyHint": True}),
            mcp_tool("srv_create-draft", {"readOnlyHint": False, "destructiveHint": True}),
            mcp_tool("srv_no-annotations"),
            mcp_tool("srv_claims-read-only", {"readOnlyHint": True}),
        ],
        read_allowlist={"srv_list-mail"},
    )

    pauses = {t.name: await pauses_for_approval(start_run, t) for t in classified}

    assert pauses == {
        "srv_list-mail": False,
        "srv_create-draft": True,
        "srv_no-annotations": True,
        "srv_claims-read-only": True,
    }


@pytest.mark.asyncio
async def test_every_bound_tool_is_read_classified_or_gated_by_approval(start_run):
    for bound_tool in LOCAL_TOOLS:  # build_graph binds LOCAL_TOOLS by default
        assert is_read(bound_tool) or await pauses_for_approval(start_run, bound_tool), bound_tool.name
