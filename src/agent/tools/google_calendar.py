# src/agent/tools/google_calendar.py
"""
Google Calendar tools for the personal data agent.

Tools:
  - list_calendar_events: fetch upcoming events in a time window
  - get_calendar_event:   fetch a single event by ID

Both tools are read-only (calendar.readonly scope). Write operations
(create, update, delete) are intentionally out of scope for now — they
would require human-in-the-loop confirmation (Phase 2.6) before it is
safe to expose them to the agent.

Authentication is delegated to agent.auth.google.get_google_credentials(),
which handles token loading, refresh, and first-run browser flow.

Error handling follows the same pattern as filesystem tools: all failures
are caught and returned as "Error: ..." strings so the agent always receives
a ToolMessage rather than a Python traceback halting the graph.
"""

import datetime

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from langchain_core.tools import StructuredTool, tool
from pydantic import BaseModel, Field

from agent.auth.google import get_google_credentials
from fixture_world import google as fixture_google


def _get_calendar_service():
    """Build and return an authenticated Google Calendar API service client."""
    creds = get_google_credentials()
    return build("calendar", "v3", credentials=creds)


# ---------------------------------------------------------------------------
# list_calendar_events
# ---------------------------------------------------------------------------

class ListCalendarEventsInput(BaseModel):
    days_ahead: int = Field(
        default=7,
        description=(
            "Number of days ahead from now to fetch events for. "
            "For example, 1 = today only, 7 = the next week, 30 = the next month. "
            "Defaults to 7."
        ),
        ge=1,
        le=90,
    )
    max_results: int = Field(
        default=10,
        description="Maximum number of events to return. Defaults to 10, maximum 50.",
        ge=1,
        le=50,
    )
    calendar_id: str = Field(
        default="primary",
        description=(
            "The calendar to query. Use 'primary' for the main calendar (default). "
            "Use a specific calendar email address to query a different calendar."
        ),
    )


@tool("list_calendar_events", args_schema=ListCalendarEventsInput)
def list_calendar_events(
    days_ahead: int = 7,
    max_results: int = 10,
    calendar_id: str = "primary",
) -> str:
    """
    List upcoming events from Google Calendar.

    Returns a formatted list of events with their title, date/time, location,
    and event ID. Use the event ID with get_calendar_event to fetch full details
    for a specific event.

    On failure returns a string beginning with "Error:".
    """
    try:
        service = _get_calendar_service()

        now = datetime.datetime.now(tz=datetime.timezone.utc)
        time_max = now + datetime.timedelta(days=days_ahead)

        result = (
            service.events()
            .list(
                calendarId=calendar_id,
                timeMin=now.isoformat(),
                timeMax=time_max.isoformat(),
                maxResults=max_results,
                singleEvents=True,      # expand recurring events into individual instances
                orderBy="startTime",
            )
            .execute()
        )

        events = result.get("items", [])

        if not events:
            return f"No events found in the next {days_ahead} day(s)."

        lines = [f"Upcoming events (next {days_ahead} day(s)):", ""]
        for event in events:
            # Events can be all-day (date) or timed (dateTime)
            start = event["start"].get("dateTime", event["start"].get("date", "Unknown"))
            end = event["end"].get("dateTime", event["end"].get("date", "Unknown"))
            title = event.get("summary", "(No title)")
            location = event.get("location", "")
            event_id = event.get("id", "")
            organizer = event.get("organizer", {}).get("email", "")

            lines.append(f"Title:    {title}")
            lines.append(f"Start:    {start}")
            lines.append(f"End:      {end}")
            if location:
                lines.append(f"Location: {location}")
            if organizer:
                lines.append(f"Organizer:{organizer}")
            lines.append(f"ID:       {event_id}")
            lines.append("")  # blank line between events

        return "\n".join(lines).rstrip()

    except HttpError as e:
        return f"Error: Google Calendar API error {e.status_code}: {e.reason}"
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"


# ---------------------------------------------------------------------------
# get_calendar_event
# ---------------------------------------------------------------------------

class GetCalendarEventInput(BaseModel):
    event_id: str = Field(
        description=(
            "The unique ID of the calendar event to retrieve. "
            "Get this from the ID field returned by list_calendar_events."
        )
    )
    calendar_id: str = Field(
        default="primary",
        description="The calendar containing the event. Defaults to 'primary'.",
    )


@tool("get_calendar_event", args_schema=GetCalendarEventInput)
def get_calendar_event(event_id: str, calendar_id: str = "primary") -> str:
    """
    Get full details of a single Google Calendar event by its ID.

    Returns all available fields: title, description, attendees, conferencing
    links, location, organizer, and status. Use this after list_calendar_events
    when you need the full content of a specific event (e.g. meeting agenda
    in the description, list of attendees, video call link).

    On failure returns a string beginning with "Error:".
    """
    try:
        service = _get_calendar_service()

        event = (
            service.events()
            .get(calendarId=calendar_id, eventId=event_id)
            .execute()
        )

        title = event.get("summary", "(No title)")
        start = event["start"].get("dateTime", event["start"].get("date", "Unknown"))
        end = event["end"].get("dateTime", event["end"].get("date", "Unknown"))
        description = event.get("description", "")
        location = event.get("location", "")
        status = event.get("status", "")
        organizer = event.get("organizer", {}).get("email", "")

        attendees = event.get("attendees", [])
        attendee_lines = [
            f"  - {a.get('email', '?')} ({a.get('responseStatus', '?')})"
            for a in attendees
        ]

        # Extract video conferencing link if present (Google Meet etc.)
        conference_link = ""
        conf_data = event.get("conferenceData", {})
        for entry in conf_data.get("entryPoints", []):
            if entry.get("entryPointType") == "video":
                conference_link = entry.get("uri", "")
                break

        lines = [
            f"Title:       {title}",
            f"Start:       {start}",
            f"End:         {end}",
            f"Status:      {status}",
            f"Organizer:   {organizer}",
        ]
        if location:
            lines.append(f"Location:    {location}")
        if conference_link:
            lines.append(f"Video call:  {conference_link}")
        if description:
            lines.append(f"Description:\n{description}")
        if attendee_lines:
            lines.append("Attendees:")
            lines.extend(attendee_lines)

        return "\n".join(lines)

    except HttpError as e:
        if e.status_code == 404:
            return f"Error: event not found (ID: {event_id})"
        return f"Error: Google Calendar API error {e.status_code}: {e.reason}"
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"


fixture_list_calendar_events = StructuredTool.from_function(
    func=fixture_google.list_calendar_events,
    name=list_calendar_events.name,
    description=list_calendar_events.description,
    args_schema=ListCalendarEventsInput,
)
fixture_get_calendar_event = StructuredTool.from_function(
    func=fixture_google.get_calendar_event,
    name=get_calendar_event.name,
    description=get_calendar_event.description,
    args_schema=GetCalendarEventInput,
)
