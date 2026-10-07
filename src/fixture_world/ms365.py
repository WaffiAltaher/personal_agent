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

Run over stdio with `python -m fixture_world.ms365`.

The server can be switched into a failure mode (down, logged out, tool error, transient
error, crash) from outside its process; see "failure injection" below.
"""

import functools
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from importlib.resources import files
from pathlib import Path
from zoneinfo import ZoneInfo

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, TextContent, ToolAnnotations

from fixture_world.clock import seed_shift

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


# --- failure injection -------------------------------------------------------------------
#
# The agent's MCP client starts a fresh stand-in process for every tool call (and one to
# list the tools), so the failure mode lives outside the process and every process reads
# it when it needs it. Two knobs, read in this order:
#
#   FIXTURE_WORLD_MS365_FAILURE_FILE=<path>  a file naming the mode: "<mode>" or "<mode> <times>".
#       Re-read by every process, so it can be switched in the middle of a run. With <times>,
#       the failure applies that many more times (the file counts down), then the server is
#       healthy again. A missing or empty file means healthy. Write it with FailureSwitch.
#   FIXTURE_WORLD_MS365_FAILURE=<mode>       a mode fixed for every process started with it,
#       e.g. `FIXTURE_WORLD_MS365_FAILURE=logged-out python -m agent.cli --fixtures "..."`.
#
# Failures reproduce what the real @softeria/ms-365-mcp-server does: tool errors are its
# `{"error": "<message>"}` text with isError, worded as it words them.

FAILURE_ENV = "FIXTURE_WORLD_MS365_FAILURE"
FAILURE_FILE_ENV = "FIXTURE_WORLD_MS365_FAILURE_FILE"


class Failure(StrEnum):
    DOWN = "down"  # the server exits before serving: it fails to start
    LOGGED_OUT = "logged-out"  # no (or an expired) MS365 login: verify-login and Graph tools fail
    TOOL_ERROR = "tool-error"  # Graph tools report a permanent Graph error (403) through MCP
    TRANSIENT = "transient"  # Graph tools report a transient Graph error (503) through MCP
    CRASH = "crash"  # the server process dies in the middle of a Graph tool call


class FailureSwitch:
    """Switches stand-in MS365 servers into a Failure mode from outside their processes.

    Start the server with `env` in its environment (the agent's fixture loader passes the
    current environment through), then `set` and `clear` the mode at any time.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)

    @property
    def env(self) -> dict[str, str]:
        return {FAILURE_FILE_ENV: str(self.path)}

    def set(self, mode: Failure | str, times: int | None = None) -> None:
        """Fail in `mode` from now on, or only the next `times` times it would apply."""
        mode = Failure(mode)
        self.path.write_text(mode if times is None else f"{mode} {times}")

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)


def take_failure(*modes: Failure) -> Failure | None:
    """The switched-on failure if it is one of `modes`; counts one use of a limited failure."""
    path = os.environ.get(FAILURE_FILE_ENV)
    spec = Path(path).read_text().split() if path and Path(path).exists() else []
    if not spec:
        fixed = os.environ.get(FAILURE_ENV)
        return Failure(fixed) if fixed and Failure(fixed) in modes else None
    failure = Failure(spec[0])
    if failure not in modes:
        return None
    if len(spec) > 1:  # limited: count this use down
        remaining = int(spec[1]) - 1
        Path(path).write_text(f"{failure} {remaining}" if remaining > 0 else "")
    return failure


def _server_error(message: str) -> CallToolResult:
    """A tool error as the real server reports it."""
    return CallToolResult(content=[TextContent(type="text", text=json.dumps({"error": message}))], isError=True)


NO_TOKEN = "No valid token found"  # the real server's error when nobody is logged in


def _failing_as_switched(fn):
    """Wrap a Graph tool so it fails as the switched-on Failure mode says."""

    @functools.wraps(fn)
    def tool(*args, **kwargs):
        failure = take_failure(Failure.LOGGED_OUT, Failure.TOOL_ERROR, Failure.TRANSIENT, Failure.CRASH)
        if failure is Failure.CRASH:
            os._exit(1)  # die mid-call, without answering
        if failure is Failure.LOGGED_OUT:
            return _server_error(NO_TOKEN)
        if failure is Failure.TOOL_ERROR:
            return _server_error('Microsoft Graph API error: 403 Forbidden - {"error":{"code":"ErrorAccessDenied",'
                                 '"message":"Access is denied. Check credentials and try again."}}')
        if failure is Failure.TRANSIENT:
            return _server_error('Microsoft Graph API error: 503 Service Unavailable - {"error":{"code":'
                                 '"ServiceNotAvailable","message":"The service is temporarily unavailable."}}')
        return fn(*args, **kwargs)

    return tool


def create_server(world: Ms365World | None = None) -> FastMCP:
    world = world or Ms365World()
    mcp = FastMCP("ms365-fixture-world", instructions="Stand-in for @softeria/ms-365-mcp-server (Fixture world).")

    def graph_tool(name: str, description: str, read_only: bool = True):
        register = mcp.tool(name=name, description=description,
                            annotations=_graph_annotations(name, read_only), structured_output=False)
        return lambda fn: register(_failing_as_switched(fn))

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
        if take_failure(Failure.LOGGED_OUT):
            return json.dumps({"success": False, "message": f"Login failed: {NO_TOKEN}"})
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
    if take_failure(Failure.DOWN):
        sys.exit("ms365 stand-in: switched down (Failure.DOWN)")
    create_server().run("stdio")


if __name__ == "__main__":
    main()
