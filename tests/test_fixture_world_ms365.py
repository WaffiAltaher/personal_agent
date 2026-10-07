"""
tests/test_fixture_world_ms365.py

Seam A against the Fixture world: the graph runs with a scripted model, and its MS365
tools are loaded over real MCP (stdio) from the stand-in MS365 server, exactly as the
CLI's `--fixtures` flag loads them. Assertions are on what the model gets to see.
"""

import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from agent.graph import build_graph
from agent.tools import load_all_tools

# The Fixture world's seeded week runs Monday 2026-10-05 to Sunday 2026-10-11.
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
async def test_meetings_this_week_combines_calendar_contacts_and_mail(fixture_tools, scripted_model):
    """'What meetings do I have this week and who is attending?' (plan item 5.3)."""
    tools = await fixture_tools()
    model = scripted_model([
        _call("ms365_get-calendar-view", {
            "startDateTime": "2026-10-05T00:00:00+02:00",
            "endDateTime": "2026-10-12T00:00:00+02:00",
            "select": "subject,start,end,organizer,attendees",
            "timezone": "Europe/Amsterdam",
        }, "calendar"),
        _call("ms365_list-outlook-contacts", {}, "contacts"),
        _call("ms365_list-mail-messages", {"search": '"route planner"'}, "mail"),
        AIMessage(content="You have three meetings this week."),
    ])
    graph = build_graph(model=model, tools=tools)

    result = await graph.ainvoke(
        {"messages": [HumanMessage(content="What meetings do I have this week and who is attending?")]}
    )

    results = _tool_results(result)
    assert all(m.status != "error" for m in results.values())

    events = _payload(results["calendar"])["value"]
    assert [e["subject"] for e in events] == [
        "Quarterly review Bakkerij De Gouden Bol",
        "Kick-off route planner Van Dijk Logistiek",
        "Website advice call",
    ]
    kickoff = events[1]
    assert kickoff["start"] == {"dateTime": "2026-10-08T15:00:00.0000000", "timeZone": "Europe/Amsterdam"}
    assert [a["emailAddress"]["address"] for a in kickoff["attendees"]] == [
        "pieter@vandijklogistiek.example",
        "eva.jansen@vandijklogistiek.example",
    ]

    contacts = {c["emailAddresses"][0]["address"]: c for c in _payload(results["contacts"])["value"]}
    assert contacts["pieter@vandijklogistiek.example"]["jobTitle"] == "Operations manager"
    assert contacts["pieter@vandijklogistiek.example"]["companyName"] == "Van Dijk Logistiek B.V."

    mail = _payload(results["mail"])["value"]
    assert [m["subject"] for m in mail] == ["Agenda for Thursday's route planner kick-off"]
    assert mail[0]["from"]["emailAddress"]["address"] == "pieter@vandijklogistiek.example"

    assert result["messages"][-1].content == "You have three meetings this week."


@pytest.mark.asyncio
async def test_seeded_week_moves_to_the_current_week(monkeypatch, scripted_model):
    """'This week' finds the seeded meetings whenever the Fixture world runs."""
    monkeypatch.setenv("FIXTURE_WORLD_TODAY", "2027-01-13")  # a Wednesday, 14 weeks on
    tools, _ = await load_all_tools(fixtures=True)
    model = scripted_model([
        _call("ms365_get-calendar-view", {
            "startDateTime": "2027-01-11T00:00:00Z",
            "endDateTime": "2027-01-18T00:00:00Z",
            "select": "subject,start",
        }, "calendar"),
        AIMessage(content="done"),
    ])

    result = await build_graph(model=model, tools=tools).ainvoke({"messages": [HumanMessage(content="this week?")]})

    events = _payload(_tool_results(result)["calendar"])["value"]
    assert [(e["subject"], e["start"]["dateTime"]) for e in events] == [
        ("Quarterly review Bakkerij De Gouden Bol", "2027-01-12T08:00:00.0000000"),
        ("Kick-off route planner Van Dijk Logistiek", "2027-01-14T13:00:00.0000000"),
        ("Website advice call", "2027-01-15T09:00:00.0000000"),
    ]


@pytest.mark.asyncio
async def test_unread_mail_filter_and_an_unsupported_filter(fixture_tools, scripted_model):
    """OData filters the agent uses work; one the stand-in can't evaluate is a Graph error, not a guess."""
    tools = await fixture_tools()
    model = scripted_model([
        _call("ms365_list-mail-messages", {
            "filter": "isRead eq false and receivedDateTime ge 2026-10-05T00:00:00Z",
            "select": "subject",
        }, "unread"),
        _call("ms365_list-outlook-contacts", {
            "filter": "emailAddresses/any(a:a/address eq 'jan@goudenbol.example')",
        }, "unsupported"),
        AIMessage(content="done"),
    ])

    result = await build_graph(model=model, tools=tools).ainvoke({"messages": [HumanMessage(content="unread?")]})

    results = _tool_results(result)
    assert [m["subject"] for m in _payload(results["unread"])["value"]] == [
        "Examples for the new website",
        "Agenda for Thursday's route planner kick-off",
    ]
    assert results["unsupported"].status == "error"
    assert "Invalid filter clause" in str(results["unsupported"].content)


@pytest.mark.asyncio
async def test_model_sees_ms365_read_tools_but_no_account_tools(fixture_tools):
    tools = await fixture_tools()

    assert sorted(t.name for t in tools if t.name.startswith("ms365_")) == [
        "ms365_get-calendar-event",
        "ms365_get-calendar-view",
        "ms365_get-mail-message",
        "ms365_get-outlook-contact",
        "ms365_list-calendar-events",
        "ms365_list-mail-messages",
        "ms365_list-outlook-contacts",
    ]
