"""
tests/test_mcp_boundary_failures.py

Seam A at the MCP boundary: a broken MCP integration never takes the agent down.
The stand-in MS365 server is switched into each failure mode from outside its process
(fixture_world.ms365.FailureSwitch), and the graph runs with a scripted model.
Assertions are on what the agent starts with and what the model gets to see.
"""

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

import agent.graph as graph_module
from agent.graph import build_graph
from agent.tools import LOCAL_TOOLS, load_all_tools
from agent.tools.ms365_mcp import PACKAGE
from fixture_world.ms365 import FailureSwitch


@pytest.fixture(autouse=True)
def no_backoff_wait(monkeypatch):
    """Keep the retry semantics but skip the real sleeps."""
    monkeypatch.setattr(
        graph_module,
        "TOOL_RETRY_POLICY",
        graph_module.TOOL_RETRY_POLICY._replace(initial_interval=0.0, jitter=False),
    )


@pytest.fixture
def ms365_failure(tmp_path, monkeypatch):
    """The stand-in MS365 server's failure switch; healthy until set."""
    monkeypatch.setenv("FIXTURE_WORLD_TODAY", "2026-10-07")
    switch = FailureSwitch(tmp_path / "ms365-failure")
    for key, value in switch.env.items():
        monkeypatch.setenv(key, value)
    return switch


def _call(name: str, args: dict, call_id: str) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"id": call_id, "name": name, "args": args}])


def _tool_results(result: dict) -> dict[str, ToolMessage]:
    return {m.tool_call_id: m for m in result["messages"] if isinstance(m, ToolMessage)}


async def _run(tools, scripted_model, *tool_calls: AIMessage) -> dict:
    model = scripted_model([*tool_calls, AIMessage(content="done")])
    return await build_graph(model=model, tools=tools).ainvoke({"messages": [HumanMessage(content="go")]})


# --- at startup ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_server_down_at_startup_leaves_the_agent_running_without_it(ms365_failure, scripted_model):
    ms365_failure.set("down")

    tools, notices = await load_all_tools(fixtures=True)

    names = {t.name for t in tools}
    assert {t.name for t in LOCAL_TOOLS} <= names
    assert any(name.startswith("informer_") for name in names)  # the other integration is unaffected
    assert not any(name.startswith("ms365_") for name in names)
    assert len(notices) == 1
    assert notices[0] == "ms365 tools unavailable: the server failed to start (McpError: Connection closed)"
    # and the agent still runs on what's left
    result = await _run(tools, scripted_model)
    assert result["messages"][-1].content == "done"


@pytest.mark.asyncio
async def test_missing_login_at_startup_names_the_login_command(ms365_failure):
    ms365_failure.set("logged-out")

    tools, notices = await load_all_tools(fixtures=True)

    assert not any(t.name.startswith("ms365_") for t in tools)
    assert len(notices) == 1
    assert notices[0].startswith("ms365 tools unavailable: not logged in to Microsoft 365")
    assert "No valid token found" in notices[0]
    assert f"npx -y {PACKAGE} --login" in notices[0]


# --- in a run -----------------------------------------------------------------------------

LIST_CONTACTS = ("ms365_list-outlook-contacts", {"select": "displayName"})


@pytest.mark.asyncio
async def test_tool_error_reported_through_mcp_reaches_the_model_and_is_not_retried(ms365_failure, scripted_model):
    tools, _ = await load_all_tools(fixtures=True)
    ms365_failure.set("tool-error", times=1)  # a retry would succeed, so success would mean it was retried

    result = await _run(tools, scripted_model, _call(*LIST_CONTACTS, "c1"))

    message = _tool_results(result)["c1"]
    assert message.status == "error"
    assert "403 Forbidden" in str(message.content)
    assert result["messages"][-1].content == "done"


@pytest.mark.asyncio
async def test_transient_error_on_a_read_tool_is_retried(ms365_failure, scripted_model):
    tools, _ = await load_all_tools(fixtures=True)
    ms365_failure.set("transient", times=1)

    result = await _run(tools, scripted_model, _call(*LIST_CONTACTS, "c1"))

    message = _tool_results(result)["c1"]
    assert message.status != "error"
    assert "Jan de Bakker" in str(message.content)


@pytest.mark.asyncio
async def test_persistent_transient_error_reaches_the_model_after_the_retries(ms365_failure, scripted_model):
    tools, _ = await load_all_tools(fixtures=True)
    ms365_failure.set("transient")

    result = await _run(tools, scripted_model, _call(*LIST_CONTACTS, "c1"))

    message = _tool_results(result)["c1"]
    assert message.status == "error"
    assert f"failed (transient) after {graph_module.TOOL_RETRY_POLICY.max_attempts} attempt(s)" in message.content
    assert "503 Service Unavailable" in message.content


@pytest.mark.asyncio
async def test_server_crash_in_the_middle_of_a_run_reaches_the_model(ms365_failure, scripted_model):
    tools, _ = await load_all_tools(fixtures=True)
    ms365_failure.set("crash")

    result = await _run(tools, scripted_model, _call(*LIST_CONTACTS, "c1"))

    message = _tool_results(result)["c1"]
    assert message.status == "error"
    assert "ms365 MCP server closed the connection" in message.content
    assert result["messages"][-1].content == "done"


@pytest.mark.asyncio
async def test_a_crashed_call_is_retried_on_a_fresh_server(ms365_failure, scripted_model):
    tools, _ = await load_all_tools(fixtures=True)
    ms365_failure.set("crash", times=1)

    result = await _run(tools, scripted_model, _call(*LIST_CONTACTS, "c1"))

    assert "Jan de Bakker" in str(_tool_results(result)["c1"].content)


@pytest.mark.asyncio
async def test_login_expiring_in_the_middle_of_a_run_names_the_login_command(ms365_failure, scripted_model):
    tools, _ = await load_all_tools(fixtures=True)
    ms365_failure.set("logged-out", times=1)  # a retry would succeed, so success would mean it was retried

    result = await _run(tools, scripted_model, _call(*LIST_CONTACTS, "c1"))

    message = _tool_results(result)["c1"]
    assert message.status == "error"
    assert "Not logged in to Microsoft 365" in str(message.content)
    assert f"npx -y {PACKAGE} --login" in str(message.content)


@pytest.mark.asyncio
async def test_server_gone_in_the_middle_of_a_run_reaches_the_model(ms365_failure, scripted_model):
    tools, _ = await load_all_tools(fixtures=True)
    ms365_failure.set("down")  # every new server process now exits before answering

    result = await _run(tools, scripted_model, _call(*LIST_CONTACTS, "c1"))

    message = _tool_results(result)["c1"]
    assert message.status == "error"
    assert "ms365 MCP server closed the connection" in message.content


# --- tracing (langfuse_spans fixture: tests/conftest.py) -----------------------------------

@pytest.mark.asyncio
async def test_mcp_tool_calls_are_langfuse_spans_named_after_the_prefixed_tool(
        ms365_failure, scripted_model, langfuse_spans):
    from agent.tracing import get_callback_handler

    tools, _ = await load_all_tools(fixtures=True)
    model = scripted_model([_call(*LIST_CONTACTS, "c1"), AIMessage(content="done")])
    handler = get_callback_handler(trace_id="0" * 31 + "1")

    await build_graph(model=model, tools=tools).ainvoke(
        {"messages": [HumanMessage(content="go")]}, config={"callbacks": [handler]})

    assert "ms365_list-outlook-contacts" in {span.name for span in langfuse_spans()}


@pytest.mark.asyncio
async def test_transient_informer_failure_is_retried_on_a_read_tool(monkeypatch, scripted_model):
    """Informer reports a transient upstream failure only as tool-error text; it is still retried."""
    monkeypatch.setenv("FIXTURE_WORLD_TODAY", "2026-10-07")
    monkeypatch.setenv("FIXTURE_WORLD_INFORMER_FAILURE", "server_error")  # the fake Informer API answers 503
    tools, _ = await load_all_tools(fixtures=True)

    result = await _run(tools, scripted_model, _call("informer_list_relations", {}, "c1"))

    message = _tool_results(result)["c1"]
    assert message.status == "error"
    assert f"failed (transient) after {graph_module.TOOL_RETRY_POLICY.max_attempts} attempt(s)" in message.content
    assert "Transient Informer failure" in message.content
