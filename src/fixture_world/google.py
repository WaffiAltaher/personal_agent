"""The Fixture world's personal Gmail and Google Calendar: seeded mail and events.

Seed files live under `data/google/`. Dates move with the Fixture-world clock (see clock.py)
so eval and test runs stay aligned with the pinned "today".
"""

import datetime
import json
from datetime import timedelta
from importlib.resources import files

from fixture_world.clock import seed_shift, today

_draft_counter = 0
_recorded_drafts: list[dict] = []


def load_seed(name: str):
    """Load a seeded Fixture world file from `fixture_world/data/google/`."""
    return json.loads((files("fixture_world") / "data" / "google" / f"{name}.json").read_text())


def _parse_iso(value: str) -> datetime.datetime:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.datetime.fromisoformat(value)


def _shift_datetime(value: str, shift: timedelta) -> str:
    dt = _parse_iso(value)
    shifted = dt + shift
    if value.endswith("Z"):
        return shifted.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return shifted.isoformat()


def _shift_event(event: dict, shift: timedelta) -> dict:
    out = {**event}
    for key in ("start", "end"):
        if "dateTime" in event[key]:
            out[key] = {"dateTime": _shift_datetime(event[key]["dateTime"], shift)}
        elif "date" in event[key]:
            d = datetime.date.fromisoformat(event[key]["date"]) + shift
            out[key] = {"date": d.isoformat()}
    return out


def _shift_message(message: dict, shift: timedelta) -> dict:
    return {**message, "date": _shift_datetime(message["date"], shift)}


def _messages() -> list[dict]:
    shift = seed_shift()
    return [_shift_message(m, shift) for m in load_seed("messages")]


def _events() -> list[dict]:
    shift = seed_shift()
    return sorted(
        (_shift_event(e, shift) for e in load_seed("calendar_events")),
        key=lambda e: e["start"].get("dateTime", e["start"].get("date", "")),
    )


def _fixture_now() -> datetime.datetime:
    """UTC 'now' anchored on the Fixture world's today (matches list window semantics)."""
    return datetime.datetime.combine(today(), datetime.time(12, 0), tzinfo=datetime.timezone.utc)


def _format_from(message: dict) -> str:
    name = message.get("fromName", "")
    addr = message["from"]
    return f"{name} <{addr}>" if name else addr


def _message_matches_query(message: dict, query: str) -> bool:
    q = query.strip()
    if not q:
        return True
    tokens = q.split()
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token == "OR" and i + 1 < len(tokens):
            return _message_matches_query(message, " ".join(tokens[:i])) or _message_matches_query(
                message, " ".join(tokens[i + 1 :])
            )
        if ":" in token:
            key, _, value = token.partition(":")
            key, value = key.lower(), value.lower()
            if key == "is" and value == "unread":
                if message.get("isRead", True):
                    return False
            elif key == "from":
                if value not in message["from"].lower() and value not in _format_from(message).lower():
                    return False
            elif key == "subject":
                if value not in message["subject"].lower():
                    return False
            elif key == "to":
                if value not in message["to"].lower():
                    return False
            elif key == "after":
                # Gmail uses YYYY/MM/DD
                parts = value.replace("-", "/").split("/")
                if len(parts) == 3:
                    y, m, d = (int(p) for p in parts)
                    cutoff = datetime.datetime(y, m, d, tzinfo=datetime.timezone.utc)
                    if _parse_iso(message["date"]) < cutoff:
                        return False
            elif key == "has":
                if value == "attachment":
                    if not any(part.get("filename") for part in message.get("parts", [])):
                        return False
            else:
                hay = " ".join(
                    (
                        message.get("subject", ""),
                        message.get("snippet", ""),
                        message.get("body", ""),
                        message["from"],
                    )
                ).lower()
                if token.lower() not in hay:
                    return False
        else:
            hay = " ".join(
                (
                    message.get("subject", ""),
                    message.get("snippet", ""),
                    message.get("body", ""),
                    message["from"],
                    message.get("fromName", ""),
                )
            ).lower()
            if token.lower() not in hay:
                return False
        i += 1
    return True


def search_gmail(query: str, max_results: int = 10) -> str:
    matches = [m for m in _messages() if _message_matches_query(m, query)]
    matches.sort(key=lambda m: m["date"], reverse=True)
    matches = matches[:max_results]

    if not matches:
        return f"No messages found for query: '{query}'"

    lines = [f"Gmail search results for '{query}':", ""]
    for msg in matches:
        lines.append(f"ID:      {msg['id']}")
        lines.append(f"From:    {_format_from(msg)}")
        lines.append(f"Date:    {msg['date']}")
        lines.append(f"Subject: {msg['subject']}")
        snippet = msg.get("snippet", "")
        if snippet:
            lines.append(f"Preview: {snippet[:120]}...")
        lines.append("")
    return "\n".join(lines).rstrip()


def get_gmail_message(message_id: str) -> str:
    for msg in _messages():
        if msg["id"] == message_id:
            body = msg.get("body", "")
            max_body_chars = 4000
            truncated = False
            if len(body) > max_body_chars:
                body = body[:max_body_chars]
                truncated = True
            lines = [
                f"From:    {_format_from(msg)}",
                f"To:      {msg['to']}",
                f"Date:    {msg['date']}",
                f"Subject: {msg['subject']}",
            ]
            cc = msg.get("cc", "")
            if cc:
                lines.append(f"Cc:      {cc}")
            lines.append("")
            lines.append(body.strip())
            if truncated:
                lines.append(f"\n[Message truncated at {max_body_chars} characters]")
            return "\n".join(lines)
    return f"Error: message not found (ID: {message_id})"


def message_payload(message_id: str) -> dict | None:
    """The message's attachment parts as a Gmail API payload, or None for an unknown message.

    Seeded `parts` have the Gmail API's shape, so the real tool's part walking runs on them."""
    for msg in _messages():
        if msg["id"] == message_id:
            return {"mimeType": "multipart/mixed", "parts": msg.get("parts", [])}
    return None


def attachment_data(message_id: str, attachment_id: str) -> str | None:
    """An attachment's bytes as the attachments endpoint returns them: base64url, unpadded."""
    for msg in _messages():
        if msg["id"] == message_id:
            return msg.get("attachmentData", {}).get(attachment_id)
    return None


def create_draft_email(to: str, subject: str, body: str, cc: str = "") -> str:
    global _draft_counter
    _draft_counter += 1
    draft_id = f"fixture-gmail-draft-{_draft_counter}"
    _recorded_drafts.append({"id": draft_id, "to": to, "subject": subject, "body": body, "cc": cc})
    return (
        f"Draft created successfully.\n"
        f"Draft ID: {draft_id}\n"
        f"To:       {to}\n"
        f"Subject:  {subject}\n"
        "The draft is saved in your Gmail Drafts folder. "
        "It has NOT been sent."
    )


def _event_start_dt(event: dict) -> datetime.datetime:
    start = event["start"]
    if "dateTime" in start:
        return _parse_iso(start["dateTime"])
    d = datetime.date.fromisoformat(start["date"])
    return datetime.datetime.combine(d, datetime.time.min, tzinfo=datetime.timezone.utc)


def _event_end_dt(event: dict) -> datetime.datetime:
    end = event["end"]
    if "dateTime" in end:
        return _parse_iso(end["dateTime"])
    d = datetime.date.fromisoformat(end["date"])
    return datetime.datetime.combine(d, datetime.time.max, tzinfo=datetime.timezone.utc)


def list_calendar_events(
    days_ahead: int = 7,
    max_results: int = 10,
    calendar_id: str = "primary",
) -> str:
    if calendar_id != "primary":
        return f"No events found in the next {days_ahead} day(s)."

    now = _fixture_now()
    time_max = now + datetime.timedelta(days=days_ahead)
    upcoming = [
        e for e in _events()
        if now <= _event_start_dt(e) <= time_max
    ][:max_results]

    if not upcoming:
        return f"No events found in the next {days_ahead} day(s)."

    lines = [f"Upcoming events (next {days_ahead} day(s)):", ""]
    for event in upcoming:
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
        lines.append("")
    return "\n".join(lines).rstrip()


def get_calendar_event(event_id: str, calendar_id: str = "primary") -> str:
    if calendar_id != "primary":
        return f"Error: event not found (ID: {event_id})"
    for event in _events():
        if event["id"] != event_id:
            continue
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

        conference_link = ""
        for entry in event.get("conferenceData", {}).get("entryPoints", []):
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
    return f"Error: event not found (ID: {event_id})"
