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

# Seeded Due dates are fixed; on the seeded Wednesday, 2265.30 EUR is overdue.
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
async def test_whats_outstanding_is_answered_from_informer(fixture_tools, scripted_model):
    """'What's outstanding?': Overdue invoices per Client, from Informer, end to end."""
    tools = await fixture_tools()
    model = scripted_model([
        _call("informer_list_overdue_invoices", {}, "overdue"),
        AIMessage(content="2265.30 EUR is overdue across three Clients."),
    ])
    graph = build_graph(model=model, tools=tools)

    result = await graph.ainvoke({"messages": [HumanMessage(content="What's outstanding?")]})

    overdue = _tool_results(result)["overdue"]
    assert overdue.status != "error"
    payload = _payload(overdue)
    assert (payload["as_of"], payload["currency"], payload["total_open_amount"]) == (SEEDED_TODAY, "EUR", "2265.30")
    assert [(c["name"], c["total_open_amount"], c["email"]) for c in payload["clients"]] == [
        ("Bakkerij De Gouden Bol B.V.", "1515.00", "administratie@goudenbol.example"),
        ("Noordzee Advies", "450.00", None),
        ("Van Dijk Logistiek B.V.", "300.30", "info@vandijklogistiek.example"),
    ]
    # A read tool: it ran without pausing for approval.
    assert "__interrupt__" not in result
    assert result["messages"][-1].content == "2265.30 EUR is overdue across three Clients."


@pytest.mark.asyncio
async def test_informer_tools_are_bound_with_the_prefix_and_all_read(fixture_tools):
    tools = await fixture_tools()

    informer_tools = [t for t in tools if t.name.startswith("informer_")]
    assert sorted(t.name for t in informer_tools) == [
        "informer_get_relation",
        "informer_get_sales_invoice",
        "informer_list_overdue_invoices",
        "informer_list_relations",
        "informer_list_sales_invoices",
        "informer_trial_balance",
    ]
    assert all(is_read(t) for t in informer_tools)


@pytest.mark.asyncio
async def test_informer_follows_a_pinned_date_outside_the_seeded_week(monkeypatch, scripted_model):
    """One "today": pinned two weeks after the seeded week, Informer's as-of date is the pinned
    date (as the model and MS365 see it), and seeded dates move along by the same two weeks,
    so the same invoices are overdue by the same number of days."""
    monkeypatch.setenv("FIXTURE_WORLD_TODAY", "2026-10-21")
    tools, notices = await load_all_tools(fixtures=True)
    assert notices == []
    model = scripted_model([_call("informer_list_overdue_invoices", {}, "overdue"), AIMessage(content="Done.")])

    result = await build_graph(model=model, tools=tools).ainvoke({"messages": [HumanMessage(content="Overdue?")]})

    payload = _payload(_tool_results(result)["overdue"])
    assert (payload["as_of"], payload["total_open_amount"]) == ("2026-10-21", "2265.30")
    invoices = {i["number"]: i for c in payload["clients"] for i in c["invoices"]}
    # seeded: invoiced 2026-08-01, due 2026-08-31, 37 days overdue on 2026-10-07
    assert (invoices["2026-0101"]["invoice_date"], invoices["2026-0101"]["due_date"],
            invoices["2026-0101"]["days_overdue"]) == ("2026-08-15", "2026-09-14", 37)
