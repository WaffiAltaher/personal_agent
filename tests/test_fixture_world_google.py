"""
tests/test_fixture_world_google.py

In Fixture-world mode the Gmail and Google Calendar tools are seeded stand-ins: same names,
arguments and Write-action classification as the real tools. Nothing reaches Google.
"""

import pytest
import pytest_asyncio

from agent.tools import LOCAL_TOOLS, load_all_tools
from agent.tools.classification import is_read
from agent.tools.gmail import create_draft_email, get_gmail_message, search_gmail
from agent.tools.google_calendar import get_calendar_event, list_calendar_events
from fixture_world.clock import SEED_TODAY

REAL_GOOGLE_TOOLS = (
    search_gmail,
    get_gmail_message,
    create_draft_email,
    list_calendar_events,
    get_calendar_event,
)
GOOGLE_TOOL_NAMES = {t.name for t in REAL_GOOGLE_TOOLS}

SEEDED_TODAY = SEED_TODAY.isoformat()


@pytest_asyncio.fixture
async def fixture_google_tools(monkeypatch):
    """Google stand-ins as `--fixtures` loads them, with the Fixture world's clock pinned."""
    monkeypatch.setenv("FIXTURE_WORLD_TODAY", SEEDED_TODAY)
    tools, notices = await load_all_tools(fixtures=True)
    assert notices == []
    return {t.name: t for t in tools if t.name in GOOGLE_TOOL_NAMES}


@pytest.mark.asyncio
async def test_fixture_world_binds_no_real_google_tool(fixture_google_tools):
    for real in REAL_GOOGLE_TOOLS:
        bound = fixture_google_tools[real.name]
        assert bound is not real
        assert bound.name == real.name
        assert (bound.tool_call_schema.model_json_schema()
                == real.tool_call_schema.model_json_schema())


@pytest.mark.asyncio
async def test_fixture_world_google_reads_are_classified_read(fixture_google_tools):
    for name in ("search_gmail", "get_gmail_message", "list_calendar_events", "get_calendar_event"):
        assert is_read(fixture_google_tools[name]), name


@pytest.mark.asyncio
async def test_fixture_world_gmail_draft_is_a_write_action(fixture_google_tools):
    assert not is_read(fixture_google_tools["create_draft_email"])


@pytest.mark.asyncio
async def test_real_mode_still_binds_the_real_google_tools():
    by_name = {t.name: t for t in LOCAL_TOOLS}
    for real in REAL_GOOGLE_TOOLS:
        assert by_name[real.name] is real


@pytest.mark.asyncio
async def test_fixture_world_search_gmail_returns_seeded_messages(fixture_google_tools):
    search = fixture_google_tools["search_gmail"]
    text = await search.ainvoke({"query": "subject:dentist check-up"})

    assert "Gmail search results for 'subject:dentist check-up':" in text
    assert "ID:      gmsg001" in text
    assert "Tandarts Centrum" in text


@pytest.mark.asyncio
async def test_fixture_world_get_gmail_message_returns_the_seeded_body(fixture_google_tools):
    get = fixture_google_tools["get_gmail_message"]
    text = await get.ainvoke({"message_id": "gmsg001"})

    assert "Subject: Reminder: dentist check-up" in text
    assert "bring your insurance card" in text


@pytest.mark.asyncio
async def test_fixture_world_list_calendar_events_returns_seeded_upcoming_events(fixture_google_tools):
    listing = fixture_google_tools["list_calendar_events"]
    text = await listing.ainvoke({"days_ahead": 7, "max_results": 5})

    assert "Upcoming events (next 7 day(s)):" in text
    assert "Title:    Yoga with Sam" in text
    assert "ID:       gevt001" in text


@pytest.mark.asyncio
async def test_fixture_world_get_calendar_event_returns_full_seeded_details(fixture_google_tools):
    get = fixture_google_tools["get_calendar_event"]
    text = await get.ainvoke({"event_id": "gevt001"})

    assert "Title:       Yoga with Sam" in text
    assert "Bring a mat" in text


@pytest.mark.asyncio
async def test_fixture_world_create_draft_email_saves_without_google(fixture_google_tools):
    draft = fixture_google_tools["create_draft_email"]
    text = await draft.ainvoke({
        "to": "friend@example.com",
        "subject": "Weekend hike",
        "body": "Fancy a walk on Saturday?",
    })

    assert text.startswith("Draft created successfully.")
    assert "fixture-gmail-draft-" in text
    assert "Weekend hike" in text


@pytest.mark.asyncio
async def test_fixture_world_google_seeded_dates_move_with_the_clock(fixture_google_tools, monkeypatch):
    monkeypatch.setenv("FIXTURE_WORLD_TODAY", "2026-10-14")  # one week after SEED_TODAY
    tools, _ = await load_all_tools(fixtures=True)
    listing = {t.name: t for t in tools}["list_calendar_events"]
    text = await listing.ainvoke({"days_ahead": 14, "max_results": 10})

    # gevt001 is seeded on 2026-10-08; shifted one week → 2026-10-15
    assert "Start:    2026-10-15T18:00:00+02:00" in text
