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
tools fail with a Graph 503 instead, creating nothing.

Send: `send-shared-mailbox-mail`, which the agent never binds and only the Informer server's
e-mail transport calls (ADR-019), takes the real tool's arguments (`userId`, and `body` with
`Message` and `SaveToSentItems`) and records every accepted call as a JSON line in the file named
by FIXTURE_WORLD_MS365_SENT; read the messages back with `sent_messages()`. The failure modes
below apply to it and record nothing; FIXTURE_WORLD_MS365_SEND_FAILURE=transient fails only the
send, with a Graph 503.

The other write tools the real server offers (send-mail, delete, move, update, calendar, rules,
folders, permissions) are served too, but not emulated, so that the agent's refusal to bind them is testable.

Attachments: `list-mail-attachments` serves the seeded attachments (`data/ms365/attachments.json`),
and `download-bytes-to-file` writes a seeded attachment's bytes to a local file, refusing a
relative path and an existing file as the real server does.

Drive: `list-drives` and `list-folder-files` serve one `business` drive, a directory named by
FIXTURE_WORLD_MS365_DRIVE (default under the temp directory), seeded from `data/ms365/drive/`
(a `Documents/ittopia/admin/2026/<Month>/` Invoice archive) when the directory doesn't exist yet.
Items are addressed by id, as the real server addresses them (`driveId`, `driveItemId`, `root` for
the root); an item's id is derived from its path, so it is the same in every process. The agent
binds neither tool: its Invoice archive wrappers call them (ADR-020).

Run over stdio with `python -m fixture_world.ms365`.

The server can be switched into a failure mode (down, logged out, tool error, transient
error, throttled (429), crash) from outside its process; see "failure injection" below.
"""

import base64
import fcntl
import functools
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from importlib.resources import as_file, files
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


# --- state shared between stand-in processes ---------------------------------------------

@contextmanager
def _exclusive(path: Path) -> Iterator[None]:
    """Hold an exclusive lock on `path` (via a `.lock` file beside it) across processes.

    Concurrent tool calls are concurrent stand-in processes, so every read-then-write of a
    shared file happens under this lock.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path.with_name(path.name + ".lock"), "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


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
    """Append one call to the Drafts file; the caller holds `_exclusive(drafts_path())`."""
    path = drafts_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as log:
        log.write(json.dumps({"tool": tool, "arguments": arguments, "draft": draft}) + "\n")


SENT_ENV = "FIXTURE_WORLD_MS365_SENT"  # JSON Lines file `send-shared-mailbox-mail` records into
SEND_FAILURE_ENV = "FIXTURE_WORLD_MS365_SEND_FAILURE"  # "transient": `send-shared-mailbox-mail` answers Graph 503
DEFAULT_SENT_PATH = Path(tempfile.gettempdir()) / "fixture_world_ms365_sent.jsonl"


def sent_path() -> Path:
    return Path(os.environ.get(SENT_ENV) or DEFAULT_SENT_PATH)


def recorded_send_calls(path: Path | str | None = None) -> list[dict]:
    """Every send call that reached the stand-in: {tool, arguments}."""
    path = Path(path) if path else sent_path()
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _addresses(recipients: list[dict] | None) -> list[str]:
    return [r["emailAddress"]["address"] for r in recipients or []]


def sent_messages(path: Path | str | None = None) -> list[dict]:
    """The messages the stand-in sent, oldest first: sender, to, cc, bcc, subject, body, attachments
    (name, content type, decoded bytes) and whether Graph saves it to Sent Items."""
    messages = []
    for call in recorded_send_calls(path):
        graph_body = call["arguments"]["body"]
        message = graph_body["Message"]
        messages.append({
            "sender": call["arguments"]["userId"],
            "to": _addresses(message.get("toRecipients")),
            "cc": _addresses(message.get("ccRecipients")),
            "bcc": _addresses(message.get("bccRecipients")),
            "subject": message.get("subject"),
            "body": (message.get("body") or {}).get("content"),
            "attachments": [
                {"name": a["name"], "content_type": a["contentType"], "content": base64.b64decode(a["contentBytes"])}
                for a in message.get("attachments") or []
            ],
            "save_to_sent_items": graph_body.get("SaveToSentItems", True),  # Graph's default
        })
    return messages


def _record_send_call(arguments: dict) -> None:
    path = sent_path()
    with _exclusive(path):
        with path.open("a") as log:
            log.write(json.dumps({"tool": "send-shared-mailbox-mail", "arguments": arguments}) + "\n")


DRIVE_ENV = "FIXTURE_WORLD_MS365_DRIVE"  # the drive's directory; seeded from data/ms365/drive/ if missing
DEFAULT_DRIVE_PATH = Path(tempfile.gettempdir()) / "fixture_world_ms365_drive"
DRIVE_ID = "b!FixtureWorldBusinessDrive"
DRIVE_PAGE_SIZE = 200  # Graph's default page size for a driveItem's children


def drive_path() -> Path:
    """The drive's directory, seeded from the Fixture world the first time it is used."""
    path = Path(os.environ.get(DRIVE_ENV) or DEFAULT_DRIVE_PATH)
    with _exclusive(path):
        if not path.exists():
            with as_file(files("fixture_world") / "data" / "ms365" / "drive") as seed:
                shutil.copytree(seed, path)
    return path


def _item_id(relative: Path) -> str:
    """A stable driveItem id for a path below the drive's root."""
    return "01FIXTURE" + hashlib.sha1(relative.as_posix().encode()).hexdigest()[:24].upper()


def _drive_items(root: Path) -> dict[str, Path]:
    """Every item of the drive by id, `root` included (also under its alias "root")."""
    items = {"root": root, _item_id(Path(".")): root}
    for path in root.rglob("*"):
        if not any(part.startswith(".") for part in path.relative_to(root).parts):  # lock files, .DS_Store
            items[_item_id(path.relative_to(root))] = path
    return items


def _visible_children(folder: Path) -> list[Path]:
    return sorted(p for p in folder.iterdir() if not p.name.startswith("."))


def _drive_item(root: Path, path: Path) -> dict:
    """A driveItem as Graph lists it: a folder facet for a folder, a file facet for a file."""
    relative = path.relative_to(root)
    stamp = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    parent = relative.parent
    item = {
        "id": _item_id(relative),
        "name": path.name,
        "createdDateTime": stamp,
        "lastModifiedDateTime": stamp,
        "webUrl": f"https://fixture-my.sharepoint.com/personal/jendo/Documents/{relative.as_posix()}",
        "parentReference": {"driveType": "business", "driveId": DRIVE_ID, "id": _item_id(parent),
                            "path": "/drive/root:" + ("" if parent == Path(".") else f"/{parent.as_posix()}")},
    }
    if path.is_dir():
        children = _visible_children(path)
        item["size"] = sum(p.stat().st_size for p in path.rglob("*") if p.is_file() and not p.name.startswith("."))
        item["folder"] = {"childCount": len(children)}
    else:
        item["size"] = path.stat().st_size
        item["file"] = {"mimeType": "application/pdf" if path.suffix.lower() == ".pdf" else "application/octet-stream"}
    return item


def _odata_list(value: str | list[str] | None) -> str | None:
    """`select`, `orderby` and `expand` as a comma-separated string (the real server takes either)."""
    return ",".join(value) if isinstance(value, list) else value


_ITEM_NOT_FOUND = ("itemNotFound", "The resource could not be found.")


def _graph_api_error(status: int, reason: str, code: str, message: str) -> CallToolResult:
    """A Graph HTTP failure as the real server reports it: the status in the text and in `_meta`."""
    graph_body = json.dumps({"error": {"code": code, "message": message}})
    text = json.dumps({"error": f"Microsoft Graph API error: {status} {reason} - {graph_body}"})
    return CallToolResult(content=[TextContent(type="text", text=text)], isError=True,
                          _meta={"http_status": status, "error_code": code})


def _new_draft(fields: dict) -> dict:
    """A Draft as Graph returns it from POST /me/messages: saved in Drafts, unsent."""
    now = datetime.combine(today(), datetime.now(timezone.utc).time(), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    number = len(recorded_drafts()) + 1  # under _exclusive(drafts_path()), held by draft_call
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
        # Attachments by message ID, as the real server lists them: Graph's `@odata.type` is
        # stripped from its responses, so a file attachment is told apart by its `contentBytes`.
        self.attachments = load_seed("attachments")


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
    THROTTLED = "throttled"  # Graph tools report throttling (429 Too Many Requests) through MCP
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
        with _exclusive(self.path):
            self.path.write_text(mode if times is None else f"{mode} {times}")

    def clear(self) -> None:
        with _exclusive(self.path):
            self.path.unlink(missing_ok=True)


def take_failure(*modes: Failure) -> Failure | None:
    """The switched-on failure if it is one of `modes`; counts one use of a limited failure."""
    path = os.environ.get(FAILURE_FILE_ENV)
    if not path:
        return _fixed_failure(modes)
    with _exclusive(Path(path)):  # the countdown is a read-then-write shared by every process
        spec = Path(path).read_text().split() if Path(path).exists() else []
        if not spec:
            return _fixed_failure(modes)
        failure = Failure(spec[0])
        if failure not in modes:
            return None
        if len(spec) > 1:  # limited: count this use down
            remaining = int(spec[1]) - 1
            Path(path).write_text(f"{failure} {remaining}" if remaining > 0 else "")
        return failure


def _fixed_failure(modes: tuple[Failure, ...]) -> Failure | None:
    fixed = os.environ.get(FAILURE_ENV)
    return Failure(fixed) if fixed and Failure(fixed) in modes else None


def _server_error(message: str) -> CallToolResult:
    """A tool error as the real server reports it."""
    return CallToolResult(content=[TextContent(type="text", text=json.dumps({"error": message}))], isError=True)


NO_TOKEN = "No valid token found"  # the real server's error when nobody is logged in

# A mail attachment's raw bytes, the one kind of target the stand-in's download-bytes-to-file serves.
_ATTACHMENT_VALUE = re.compile(r"/me/messages/(?P<message>[^/]+)/attachments/(?P<attachment>[^/]+)/\$value")


def _failing_as_switched(fn):
    """Wrap a Graph tool so it fails as the switched-on Failure mode says."""

    @functools.wraps(fn)
    def tool(*args, **kwargs):
        failure = take_failure(Failure.LOGGED_OUT, Failure.TOOL_ERROR, Failure.TRANSIENT, Failure.THROTTLED,
                               Failure.CRASH)
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
        if failure is Failure.THROTTLED:
            return _server_error('Microsoft Graph API error: 429 Too Many Requests - {"error":{"code":'
                                 '"TooManyRequests","message":"Please retry again later."}}')
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

    @graph_tool("list-mail-attachments", "Retrieve a list of attachment objects.")
    def list_mail_attachments(messageId: str, top: int | None = None, skip: int | None = None,
                              search: str | None = None, filter: str | None = None, orderby: str | None = None,
                              select: str | None = None) -> CallToolResult:
        if not any(m["id"] == messageId for m in world.messages):
            return _graph_error("ErrorItemNotFound", "The specified object was not found in the store.")
        return _list(world.attachments.get(messageId, []),
                     filter=filter, search=search, orderby=orderby, select=select, top=top, skip=skip)

    # --- contacts ---

    @graph_tool("list-outlook-contacts", "Get a contact collection from the default contacts folder of the signed-in user.")
    def list_outlook_contacts(top: int | None = None, skip: int | None = None, search: str | None = None,
                              filter: str | None = None, orderby: str | None = None,
                              select: str | None = None) -> CallToolResult:
        return _list(world.contacts, filter=filter, search=search, orderby=orderby, select=select, top=top, skip=skip)

    @graph_tool("get-outlook-contact", "Retrieve the properties and relationships of a contact object.")
    def get_outlook_contact(contactId: str, select: str | None = None) -> CallToolResult:
        return _get(world.contacts, contactId, select)

    # --- drive (the agent binds neither: its Invoice archive wrappers call them, ADR-020) ---

    @graph_tool("list-drives",
                "Retrieve the list of Drive resources available for a target User, Group, or Site.")
    def list_drives(top: int | None = None, skip: int | None = None, search: str | None = None,
                    filter: str | None = None, count: bool | None = None,
                    orderby: str | list[str] | None = None, select: str | list[str] | None = None,
                    expand: str | list[str] | None = None, fetchAllPages: bool | None = None,
                    skiptoken: str | None = None, includeHeaders: bool | None = None,
                    excludeResponse: bool | None = None) -> CallToolResult:
        drive = {"id": DRIVE_ID, "driveType": "business", "name": "Documenten", "description": "",
                 "owner": {"user": {"displayName": OWNER["displayName"], "email": OWNER["userPrincipalName"]}},
                 "webUrl": "https://fixture-my.sharepoint.com/personal/jendo/Documents"}
        return _list([drive], filter=filter, search=search, orderby=_odata_list(orderby),
                     select=_odata_list(select), top=top, skip=skip)

    @graph_tool("list-folder-files",
                "Return a collection of DriveItems in the children relationship of a DriveItem. DriveItems "
                "with a non-null folder or package facet can have one or more child DriveItems.")
    def list_folder_files(driveId: str, driveItemId: str, top: int | None = None, skip: int | None = None,
                          search: str | None = None, filter: str | None = None, count: bool | None = None,
                          orderby: str | list[str] | None = None, select: str | list[str] | None = None,
                          expand: str | list[str] | None = None, fetchAllPages: bool | None = None,
                          skiptoken: str | None = None, includeHeaders: bool | None = None,
                          excludeResponse: bool | None = None) -> CallToolResult:
        root = drive_path()
        folder = _drive_items(root).get(driveItemId) if driveId == DRIVE_ID else None
        if folder is None:
            return _graph_api_error(404, "Not Found", *_ITEM_NOT_FOUND)
        children = [_drive_item(root, p) for p in _visible_children(folder)] if folder.is_dir() else []
        try:
            found = _order(_search(_filter(children, filter), search), _odata_list(orderby))
        except BadRequest as exc:
            return _graph_error("BadRequest", str(exc))
        if not fetchAllPages:
            found = found[skip or 0:(skip or 0) + (top or DRIVE_PAGE_SIZE)]
        return _ok({"value": _select(found, _odata_list(select))})

    # --- Drafts (Write actions; the real server annotates POST tools readOnlyHint false) ---

    def draft_call(tool: str, arguments: dict, create) -> CallToolResult:
        # Numbering a Draft reads the file it is then recorded in: one process at a time.
        with _exclusive(drafts_path()):
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

    # --- Send (a Write action the agent never binds; the Informer server's e-mail transport calls it) ---

    @graph_tool("send-shared-mailbox-mail",
                "Send the message specified in the request body using either JSON or MIME format. When using "
                "JSON format, you can include a file attachment in the same sendMail action call. When using "
                "MIME format: This method saves the message in the Sent Items folder. Alternatively, create a "
                "draft message to send later.", read_only=False)
    def send_shared_mailbox_mail(userId: str, body: dict, includeHeaders: bool = False,
                                 excludeResponse: bool = False, confirm: bool = False) -> CallToolResult:
        if os.environ.get(SEND_FAILURE_ENV) == "transient":
            return _graph_api_error(503, "Service Unavailable", "ServiceUnavailable",
                                    "The service is temporarily unavailable. Please retry later.")
        content_type = ((body.get("Message") or {}).get("body") or {}).get("contentType")
        if content_type not in (None, "text", "html"):  # the pinned server's schema: lowercase only
            return _server_error(f"MCP error -32602: Input validation error: Invalid arguments for tool "
                                 f"send-shared-mailbox-mail: body.Message.body.contentType: Invalid option: "
                                 f'expected one of "text"|"html", received "{content_type}"')
        if not body.get("Message"):
            return _graph_api_error(400, "Bad Request", "ErrorInvalidRequest", "The request is missing a Message.")
        _record_send_call({"userId": userId, "body": body})
        return _ok({"message": "OK!"})

    # --- the real server's other writes: present, never emulated ---

    def unemulated(name: str):
        def tool() -> CallToolResult:
            return _graph_error("NotSupported", f"{name} is not emulated by the Fixture world.")
        return tool

    for name in UNEMULATED_WRITE_TOOLS:
        graph_tool(name, f"{name} (not emulated by the Fixture world)", read_only=False)(unemulated(name))

    # A local-file write that the real server annotates readOnlyHint (its method is GET). Emulated
    # for mail attachments only, with the real server's rules: outputPath must be absolute, and an
    # existing file is never overwritten.
    @mcp.tool(name="download-bytes-to-file", structured_output=False,
              description="Write authenticated Microsoft Graph byte content to a local file on the server.",
              annotations=ToolAnnotations(title="download-bytes-to-file", readOnlyHint=True, openWorldHint=True))
    @_failing_as_switched
    def download_bytes_to_file(target: str, outputPath: str) -> CallToolResult:
        if not target.startswith("/"):
            return _server_error('target must be a relative Microsoft Graph path starting with "/".')
        if not os.path.isabs(outputPath):
            return _server_error(f"outputPath must be an absolute path, e.g. /Users/me/downloads/file.ext. "
                                 f"Received: {outputPath}")
        if os.path.lexists(outputPath):
            return _server_error(f"file already exists at {outputPath}")
        match = _ATTACHMENT_VALUE.fullmatch(target)
        attachment = match and next((a for a in world.attachments.get(match["message"], [])
                                     if a["id"] == match["attachment"]), None)
        if not attachment or "contentBytes" not in attachment:
            return _server_error('Microsoft Graph API error: 404 Not Found - {"error":{"code":"ErrorItemNotFound",'
                                 '"message":"The specified object was not found in the store."}}')
        data = base64.b64decode(attachment["contentBytes"])
        try:
            with open(outputPath, "xb") as f:
                f.write(data)
        except OSError as exc:
            return _server_error(str(exc))
        return _ok({"path": outputPath, "contentType": attachment["contentType"], "bytesWritten": len(data)})

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
