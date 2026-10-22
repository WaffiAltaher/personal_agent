"""
tests/test_fixture_world_informer.py

Seam A against the Fixture world: the graph runs with a scripted model, and its Informer
tools are loaded over real MCP (stdio) from the Informer MCP server we authored, pointed at
the fake Informer API, exactly as the CLI's `--fixtures` flag loads them.
"""

import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from agent.graph import build_graph
from agent.tools import load_all_tools
from agent.tools.classification import is_read

SEEDED_TODAY = "2026-10-07"


def _call(name: str, args: dict, call_id: str) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"id": call_id, "name": name, "args": args}])


def _payload(message: ToolMessage):
    """The JSON body of an MCP tool result, as the model sees it."""
    content = message.content
    text = content if isinstance(content, str) else "".join(block["text"] for block in content)
    return json.loads(text)


def _tool_results(result: dict) -> dict[str, ToolMessage]:
    return {m.tool_call_id: m for m in result["messages"] if isinstance(m, ToolMessage)}


@pytest.fixture
def fixture_tools(monkeypatch):
    """The agent's tools as `--fixtures` loads them, with the Fixture world's clock pinned."""
    monkeypatch.setenv("FIXTURE_WORLD_TODAY", SEEDED_TODAY)

    async def _load():
        tools, notices = await load_all_tools(fixtures=True)
        assert notices == []
        return tools

    return _load


@pytest.mark.asyncio
async def test_trial_balance_is_read_from_informer_end_to_end(fixture_tools, scripted_model):
    tools = await fixture_tools()
    model = scripted_model([
        _call("informer_trial_balance", {"year": 2026}, "tb"),
        AIMessage(content="Bank balance and software spend are in the trial balance."),
    ])
    graph = build_graph(model=model, tools=tools)

    result = await graph.ainvoke({"messages": [HumanMessage(content="2026 trial balance?")]})

    tb = _tool_results(result)["tb"]
    assert tb.status != "error"
    payload = _payload(tb)
    assert payload["year"] == 2026
    assert "__interrupt__" not in result


@pytest.mark.asyncio
async def test_informer_tools_are_bound_with_the_prefix_and_all_read(fixture_tools):
    tools = await fixture_tools()

    informer_tools = [t for t in tools if t.name.startswith("informer_")]
    assert sorted(t.name for t in informer_tools) == [
        "informer_check_purchase_invoice",
        "informer_get_relation",
        "informer_get_sales_invoice",
        "informer_list_relations",
        "informer_list_sales_invoices",
        "informer_revenue",
        "informer_trial_balance",
        "informer_upload_purchase_invoice",
        "informer_vat_position",
    ]
    upload = next(t for t in informer_tools if t.name == "informer_upload_purchase_invoice")
    assert not is_read(upload)
    assert all(is_read(t) for t in informer_tools if t is not upload)
