# src/fixture_world/ms365.py
"""Stand-in MS365 MCP server: the Fixture world's mailbox, calendar and contacts.

Reproduces `@softeria/ms-365-mcp-server` for the tools the agent uses, so the same
agent code runs against both:
- the same tool names (kebab-case, e.g. `get-calendar-view`), parameter names
  (OData options without the `$`: `top`, `select`, `filter`, `search`, `orderby`)
  and annotations (Graph GET tools are `readOnlyHint: true`);
- the same response shape: the Graph JSON body as one text block, pretty-printed,
  with list results under `value`, and Graph error bodies as tool errors.

Only what the tools need is emulated: `$filter` understands comparisons (`eq`, `ne`,
`gt`, `ge`, `lt`, `le`), `contains()` and `startswith()` joined by `and`; `$search` is a case-insensitive phrase match over
the item's text fields. Seeded dates move with the Fixture world clock (see clock.py).

Drafts: `create-draft-email` and `create-reply-draft` record every call, and the Draft it
created, as a JSON line in the file named by FIXTURE_WORLD_MS365_DRAFTS (each tool call runs
in a fresh process, so the record lives outside it); read it back with `recorded_drafts()`
and `recorded_draft_calls()`. FIXTURE_WORLD_MS365_DRAFT_FAILURE=transient makes the draft
tools fail with a Graph 503 instead, creating nothing. The other write tools the real server
offers (send, delete, move, update, calendar, rules, folders, permissions) are served too, but
not emulated, so that the agent's refusal to bind them is testable.

Run over stdio with `python -m fixture_world.ms365`.
"""

import json
import os
import re
import tempfile
from datetime import datetime, timedelta, timezone
from importlib.resources import files
from pathlib import Path
from zoneinfo import ZoneInfo

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, TextContent, ToolAnnotations

from fixture_world.clock import seed_shift, today

OWNER = {"displayName": "Jen Do", "userPrincipalName": "jendo@example.com"}
DEFAULT_PAGE_SIZE = 10  # Graph's default $top


def load_seed(name: str):
    """Load a seeded Fixture world file from `fixture_world/data/ms365/`."""
    return json.loads((files("fixture_world") / "data" / "ms365" / f"{name}.json").read_text())


def _graph_annotations(name: str, read_only: bool) -> ToolAnnotations:
    """The annotations the real server gives a Graph tool (title, readOnlyHint for GET)."""
    return ToolAnnotations(title=name, readOnlyHint=read_only, destructiveHint=not read_only, openWorldHint=True)


# --- Graph emulation ---------------------------------------------------------------

def _ok(body: dict) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=json.dumps(body, indent=2))])


def _graph_error(code: str, message: str) -> CallToolResult:
    body = {"error": {"code": code, "message": message}}
    return CallToolResult(content=[TextContent(type="text", text=json.dumps(body))], isError=True)


class BadRequest(Exception):
    pass


def _field(item: dict, path: str):
    value = item
    for part in path.split("/"):
        value = value.get(part) if isinstance(value, dict) else None
    return value


def _literal(text: str):
    text = text.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}(T[\d:.]+Z?)?", text):  # unquoted date-time literal
        return text
    if text.startswith("'") and text.endswith("'"):
        return text[1:-1].replace("''", "'")
    if text in ("true", "false"):
        return text == "true"
    if text == "null":
        return None
    try:
        return float(text)
    except ValueError:
        raise BadRequest(f"Invalid filter clause: unsupported literal {text}") from None


_FUNCTION = re.compile(r"(contains|startswith)\(\s*([\w/]+)\s*,\s*('(?:[^']|'')*')\s*\)", re.IGNORECASE)
_COMPARISON = re.compile(r"([\w/]+)\s+(eq|ne|gt|ge|lt|le)\s+(.+)", re.IGNORECASE)
_COMPARE = {
    "eq": lambda a, b: a == b, "ne": lambda a, b: a != b,
    "gt": lambda a, b: a > b, "ge": lambda a, b: a >= b,
    "lt": lambda a, b: a < b, "le": lambda a, b: a <= b,
}


def _clause_matches(item: dict, clause: str) -> bool:
    clause = clause.strip()
    if match := _FUNCTION.fullmatch(clause):
        function, path, literal = match.groups()
        value = str(_field(item, path) or "").lower()
        needle = _literal(literal).lower()
        return needle in value if function.lower() == "contains" else value.startswith(needle)
    if match := _COMPARISON.fullmatch(clause):
        path, operator, literal = match.groups()
        value, expected = _field(item, path), _literal(literal)
        if isinstance(value, str) and isinstance(expected, str):
            value, expected = value.lower(), expected.lower()  # ISO date-times compare as text
        elif operator.lower() not in ("eq", "ne") and (value is None or type(value) is not type(expected)):
            return False
        return _COMPARE[operator.lower()](value, expected)
    raise BadRequest(f"Invalid filter clause: {clause}")


def _filter(items: list[dict], expression: str | None) -> list[dict]:
    if not expression:
        return items
    clauses = re.split(r"\s+and\s+", expression, flags=re.IGNORECASE)
    return [item for item in items if all(_clause_matches(item, c) for c in clauses)]


def _strings(value) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _strings(v)]
    if isinstance(value, list):
        return [s for v in value for s in _strings(v)]
    return []


def _search(items: list[dict], query: str | None) -> list[dict]:
    if not query:
        return items
    phrase = query.strip().strip('"').lower()
    return [item for item in items if any(phrase in s.lower() for s in _strings(item))]


def _order(items: list[dict], orderby: str | None) -> list[dict]:
    if not orderby:
        return items
    path, _, direction = orderby.strip().partition(" ")
    return sorted(items, key=lambda i: str(_field(i, path) or ""), reverse=direction.strip().lower() == "desc")


def _select(items: list[dict], select: str | None) -> list[dict]:
    if not select:
        return items
    fields = ["id", *(f.strip() for f in select.split(",") if f.strip() and f.strip() != "id")]
    return [{f: item[f] for f in fields if f in item} for item in items]


def _page(items: list[dict], top: int | None, skip: int | None) -> list[dict]:
    start = skip or 0
    return items[start:start + (top or DEFAULT_PAGE_SIZE)]


def _list(items, *, filter=None, search=None, orderby=None, select=None, top=None, skip=None) -> CallToolResult:
    try:
        found = _order(_search(_filter(items, filter), search), orderby)
    except BadRequest as exc:
        return _graph_error("BadRequest", str(exc))
    return _ok({"value": _select(_page(found, top, skip), select)})


def _get(items: list[dict], item_id: str, select: str | None) -> CallToolResult:
    for item in items:
        if item["id"] == item_id:
            return _ok(_select([item], select)[0])
    return _graph_error("ErrorItemNotFound", "The specified object was not found in the store.")


# --- dates ---------------------------------------------------------------------------

def _parse(value: str) -> datetime:
    """A Graph or ISO 8601 date-time; naive values are UTC, as Graph treats them."""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _graph_datetime(moment: datetime, zone: str) -> dict:
    local = moment.astimezone(ZoneInfo(zone))
    return {"dateTime": local.strftime("%Y-%m-%dT%H:%M:%S.0000000"), "timeZone": zone}


def _shift_event(event: dict, shift: timedelta) -> dict:
    return {**event, **{key: _graph_datetime(_parse(event[key]["dateTime"]) + shift, "UTC") for key in ("start", "end")}}


def _shift_message(message: dict, shift: timedelta) -> dict:
    return {**message, **{
        key: (_parse(message[key]) + shift).strftime("%Y-%m-%dT%H:%M:%SZ")
        for key in ("receivedDateTime", "sentDateTime") if message.get(key)
    }}


def _in_zone(event: dict, zone: str | None) -> dict:
    """Event times in the requested IANA zone (the real server's `timezone` option); UTC otherwise."""
    if not zone:
        return event
    return {**event, **{key: _graph_datetime(_parse(event[key]["dateTime"]), zone) for key in ("start", "end")}}


# --- Drafts ----------------------------------------------------------------------------

DRAFTS_ENV = "FIXTURE_WORLD_MS365_DRAFTS"  # JSON Lines file the draft tools record into
DRAFT_FAILURE_ENV = "FIXTURE_WORLD_MS365_DRAFT_FAILURE"  # "transient": draft calls answer Graph 503
DEFAULT_DRAFTS_PATH = Path(tempfile.gettempdir()) / "fixture_world_ms365_drafts.jsonl"


def drafts_path() -> Path:
    return Path(os.environ.get(DRAFTS_ENV) or DEFAULT_DRAFTS_PATH)


def recorded_draft_calls(path: Path | str | None = None) -> list[dict]:
    """Every draft-tool call that reached the stand-in: {tool, arguments, draft (None if it failed)}."""
    path = Path(path) if path else drafts_path()
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def recorded_drafts(path: Path | str | None = None) -> list[dict]:
    """The Drafts the stand-in created, oldest first, as Graph returned them."""
    return [call["draft"] for call in recorded_draft_calls(path) if call["draft"]]


def _record_draft_call(tool: str, arguments: dict, draft: dict | None) -> None:
    path = drafts_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as log:
        log.write(json.dumps({"tool": tool, "arguments": arguments, "draft": draft}) + "\n")


def _graph_api_error(status: int, reason: str, code: str, message: str) -> CallToolResult:
    """A Graph HTTP failure as the real server reports it: the status in the text and in `_meta`."""
    graph_body = json.dumps({"error": {"code": code, "message": message}})
    text = json.dumps({"error": f"Microsoft Graph API error: {status} {reason} - {graph_body}"})
    return CallToolResult(content=[TextContent(type="text", text=text)], isError=True,
                          _meta={"http_status": status, "error_code": code})


def _new_draft(fields: dict) -> dict:
    """A Draft as Graph returns it from POST /me/messages: saved in Drafts, unsent."""
    now = datetime.combine(today(), datetime.now(timezone.utc).time(), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    number = len(recorded_drafts()) + 1
    return {
        "id": f"AAMkAGZpeHR1cmUADRAFT{number:02d}",
        "createdDateTime": now,
        "lastModifiedDateTime": now,
        "subject": "",
        "body": {"contentType": "text", "content": ""},
        "toRecipients": [],
        "ccRecipients": [],
        "bccRecipients": [],
        "importance": "normal",
        **fields,
        "from": {"emailAddress": {"name": OWNER["displayName"], "address": OWNER["userPrincipalName"]}},
        "isDraft": True,
        "isRead": True,
    }


def _quoted(message: dict) -> str:
    sender = message["from"]["emailAddress"]
    original = "\n".join(f"> {line}" for line in message["body"]["content"].splitlines())
    return f"On {message['sentDateTime']}, {sender['name']} <{sender['address']}> wrote:\n{original}"


# The real server's other write tools in the `outlook` preset. Served (not emulated) so a
# test can prove the agent never binds them.
UNEMULATED_WRITE_TOOLS = (
    "send-mail",
    "send-draft-message",
    "reply-mail-message",
    "reply-all-mail-message",
    "forward-mail-message",
    "create-reply-all-draft",
    "create-forward-draft",
    "update-mail-message",
    "move-mail-message",
    "delete-mail-message",
    "create-mail-folder",
    "create-mail-rule",
    "create-calendar-event",
    "update-calendar-event",
    "delete-calendar-event",
    "accept-calendar-event",
    "create-outlook-contact",
    "update-my-calendar-permission",
)


# --- the world and the server ----------------------------------------------------------

class Ms365World:
    """The seeded mailbox, calendar and contacts, with dates moved onto the current week."""

    def __init__(self, shift: timedelta | None = None):
        shift = seed_shift() if shift is None else shift
        self.events = sorted(
            (_shift_event(e, shift) for e in load_seed("calendar_events")),
            key=lambda e: _parse(e["start"]["dateTime"]),
        )
        self.messages = sorted(
            (_shift_message(m, shift) for m in load_seed("messages")),
            key=lambda m: m["receivedDateTime"],
            reverse=True,  # Graph lists mail newest first
        )
        self.contacts = load_seed("contacts")


def create_server(world: Ms365World | None = None) -> FastMCP:
    world = world or Ms365World()
    mcp = FastMCP("ms365-fixture-world", instructions="Stand-in for @softeria/ms-365-mcp-server (Fixture world).")

    def graph_tool(name: str, description: str, read_only: bool = True):
        return mcp.tool(name=name, description=description,
                        annotations=_graph_annotations(name, read_only), structured_output=False)

    # --- calendar ---

    @graph_tool("get-calendar-view",
                "Get the occurrences, exceptions, and single instances of events in a calendar view "
                "defined by a time range, from the user's default calendar. Requires startDateTime and "
                "endDateTime in ISO 8601 format.")
    def get_calendar_view(startDateTime: str, endDateTime: str, top: int | None = None, skip: int | None = None,
                          search: str | None = None, filter: str | None = None, orderby: str | None = None,
                          select: str | None = None, timezone: str | None = None) -> CallToolResult:
        start, end = _parse(startDateTime), _parse(endDateTime)
        in_range = [e for e in world.events
                    if _parse(e["start"]["dateTime"]) < end and _parse(e["end"]["dateTime"]) > start]
        return _list([_in_zone(e, timezone) for e in in_range],
                     filter=filter, search=search, orderby=orderby, select=select, top=top, skip=skip)

    @graph_tool("list-calendar-events",
                "Get a list of event objects in the user's mailbox. Does NOT expand recurring events.")
    def list_calendar_events(top: int | None = None, skip: int | None = None, search: str | None = None,
                             filter: str | None = None, orderby: str | None = None, select: str | None = None,
                             timezone: str | None = None) -> CallToolResult:
        return _list([_in_zone(e, timezone) for e in world.events],
                     filter=filter, search=search, orderby=orderby, select=select, top=top, skip=skip)

    @graph_tool("get-calendar-event", "Get the properties and relationships of the specified event object.")
    def get_calendar_event(eventId: str, select: str | None = None,
                           timezone: str | None = None) -> CallToolResult:
        return _get([_in_zone(e, timezone) for e in world.events], eventId, select)

    # --- mail ---

    @graph_tool("list-mail-messages",
                "List, read and search Outlook emails across folders. Use search with a quoted KQL "
                "phrase, or filter (e.g. isRead eq false).")
    def list_mail_messages(top: int | None = None, skip: int | None = None, search: str | None = None,
                           filter: str | None = None, orderby: str | None = None,
                           select: str | None = None) -> CallToolResult:
        return _list(world.messages, filter=filter, search=search, orderby=orderby, select=select, top=top, skip=skip)

    @graph_tool("get-mail-message", "Get the properties and relationships of a message object.")
    def get_mail_message(messageId: str, select: str | None = None) -> CallToolResult:
        return _get(world.messages, messageId, select)

    # --- contacts ---

    @graph_tool("list-outlook-contacts", "Get a contact collection from the default contacts folder of the signed-in user.")
    def list_outlook_contacts(top: int | None = None, skip: int | None = None, search: str | None = None,
                              filter: str | None = None, orderby: str | None = None,
                              select: str | None = None) -> CallToolResult:
        return _list(world.contacts, filter=filter, search=search, orderby=orderby, select=select, top=top, skip=skip)

    @graph_tool("get-outlook-contact", "Retrieve the properties and relationships of a contact object.")
    def get_outlook_contact(contactId: str, select: str | None = None) -> CallToolResult:
        return _get(world.contacts, contactId, select)

    # --- Drafts (Write actions; the real server annotates POST tools readOnlyHint false) ---

    def draft_call(tool: str, arguments: dict, create) -> CallToolResult:
        if os.environ.get(DRAFT_FAILURE_ENV) == "transient":
            _record_draft_call(tool, arguments, None)
            return _graph_api_error(503, "Service Unavailable", "ServiceUnavailable",
                                    "The service is temporarily unavailable. Please retry later.")
        result = create()
        if isinstance(result, CallToolResult):  # a Graph error: nothing created
            _record_draft_call(tool, arguments, None)
            return result
        _record_draft_call(tool, arguments, result)
        return _ok(result)

    @graph_tool("create-draft-email",
                "Create a draft Outlook email message in the signed-in user's Drafts folder. Set subject, "
                "body, toRecipients, ccRecipients, and importance. The draft is saved, not sent — use "
                "send-mail to send a message directly, or send the draft afterwards.", read_only=False)
    def create_draft_email(body: dict) -> CallToolResult:
        return draft_call("create-draft-email", {"body": body}, lambda: _new_draft(body))

    @graph_tool("create-reply-draft",
                "Create a draft to reply to the sender of a message. Specify either a comment or the body "
                "property of the message parameter. Specifying both will return an HTTP 400 Bad Request error.",
                read_only=False)
    def create_reply_draft(messageId: str, body: dict | None = None) -> CallToolResult:
        body = body or {}
        # Graph action parameters are case-insensitive; the real server's schema spells them Comment/Message.
        params = {key.lower(): value for key, value in body.items()}
        comment, message = params.get("comment"), params.get("message") or {}

        def create():
            original = next((m for m in world.messages if m["id"] == messageId), None)
            if original is None:
                return _graph_error("ErrorItemNotFound", "The specified object was not found in the store.")
            if comment is not None and message.get("body"):
                return _graph_error("BadRequest", "Specify either comment or message body, not both.")
            reply_body = message.get("body") or {
                "contentType": "text",
                "content": f"{comment or ''}\n\n{_quoted(original)}".lstrip(),
            }
            return _new_draft({
                "subject": f"RE: {original['subject']}",
                "toRecipients": original.get("replyTo") or [original["from"]],
                "conversationId": original["conversationId"],
                **message,
                "body": reply_body,
            })

        return draft_call("create-reply-draft", {"messageId": messageId, "body": body}, create)

    # --- the real server's other writes: present, never emulated ---

    def unemulated(name: str):
        def tool() -> CallToolResult:
            return _graph_error("NotSupported", f"{name} is not emulated by the Fixture world.")
        return tool

    for name in UNEMULATED_WRITE_TOOLS:
        graph_tool(name, f"{name} (not emulated by the Fixture world)", read_only=False)(unemulated(name))

    # A local-file write that the real server annotates readOnlyHint (its method is GET).
    mcp.tool(name="download-bytes-to-file", structured_output=False,
             description="Write authenticated Microsoft Graph byte content to a local file on the server.",
             annotations=ToolAnnotations(title="download-bytes-to-file", readOnlyHint=True, openWorldHint=True),
             )(unemulated("download-bytes-to-file"))

    # --- account tools: present like on the real server, so the agent's hiding of them is testable ---

    def account_tool(name: str, description: str, read_only: bool):
        return mcp.tool(name=name, description=description, structured_output=False,
                        annotations=ToolAnnotations(title=name, readOnlyHint=read_only, openWorldHint=False))

    @account_tool("login", "Authenticate with Microsoft account", read_only=False)
    def login(force: bool = False) -> str:
        return json.dumps({"status": "Already logged in", **OWNER})

    @account_tool("logout", "Log out from Microsoft account", read_only=False)
    def logout() -> str:
        return json.dumps({"message": "Logged out successfully"})

    @account_tool("verify-login", "Check current Microsoft authentication status", read_only=True)
    def verify_login() -> str:
        return json.dumps({"success": True, "message": "Login successful", "userData": OWNER})

    @account_tool("list-accounts", "List all Microsoft accounts configured in this server.", read_only=True)
    def list_accounts() -> str:
        return json.dumps({"accounts": [{"username": OWNER["userPrincipalName"], "selected": True}]})

    @account_tool("select-account", "Select a Microsoft account as the default.", read_only=False)
    def select_account(account: str) -> str:
        return json.dumps({"success": True, "message": f"Selected account: {account}"})

    @account_tool("remove-account", "Remove a Microsoft account from the cache.", read_only=False)
    def remove_account(account: str) -> str:
        return json.dumps({"success": True, "message": f"Removed account: {account}"})

    return mcp


def main() -> None:
    """Run the stand-in over stdio, as the real server runs under npx."""
    create_server().run("stdio")


if __name__ == "__main__":
    main()
