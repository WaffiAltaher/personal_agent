# src/agent/tools/ms365_invoice_archive.py
"""
The Invoice archive (`Documents/ittopia/admin/<year>/<Month>/` in the owner's OneDrive, ADR-020).

Agent-side tools over the MS365 server's drive tools, which are enabled but never bound, so the
model reaches only the Invoice archive and never a drive or item id:
- `ms365_list_invoice_archive(year, month=None)` (read): the names and sizes in a month's folder,
  or a year's month folders and their file names. It matches names only.
- `ms365_check_invoice_archive(path, invoice_date)` (read, the Processed check): whether a local
  PDF's contents are in the month folder of its invoice date, comparing OneDrive's `quickXorHash`
  with one computed locally (never downloading), and if not, the target path an Upload to OneDrive
  would use, with OneDrive's rename when a different file has the name. The local file rules
  (`read_local_pdf`: a `.pdf` with the PDF magic, inside the Downloads folder the Informer server
  checks, at most 25 MB) are applied before any server call.
- `ms365_upload_to_onedrive(path, invoice_date, target_path)` (Write action, the Upload to
  OneDrive): refuses unless `target_path` is the Processed check's target path, does nothing for
  contents already in the month folder (`NOT UPLOADED:`), creates a missing year and month folder,
  starts an upload session (`rename`, never overwriting) and PUTs the bytes through a seam
  (`httpx_put` against OneDrive). The session's `uploadUrl` is a bearer capability: it never reaches
  a result, an error, a log line or a trace (`create-upload-session` is called without the run's
  callbacks). A failure is reported, never raised: a Write action is never retried.

Locating the archive: the drive is the single `business` drive from `list-drives`; folders are
found level by level by id with `list-folder-files`, starting at `root`, names matched
case-insensitively, as OneDrive matches them. A missing `Documents/ittopia/admin` is an error
(it is never created); a missing year or month means the archive holds nothing there.

Every refusal or failure is a string starting with "Error:". A transient failure of a read is
raised, so the graph retries the read.
"""

import json
import logging
import re
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import httpx
from langchain_core.messages import ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field

from agent.config import settings
from agent.tools.classification import READ
from agent.tools.mcp_loader import ToolWrapper, TransientMcpError
from agent.tools.quickxorhash import quick_xor_hash

LIST_DRIVES_TOOL = "list-drives"
LIST_FOLDER_TOOL = "list-folder-files"

ARCHIVE_FOLDERS = ("Documents", "ittopia", "admin")
ARCHIVE_PATH = "/".join(ARCHIVE_FOLDERS)
# Month folder names, in English whatever the system locale.
MONTHS = ("January", "February", "March", "April", "May", "June",
          "July", "August", "September", "October", "November", "December")


class ArchiveError(Exception):
    """The archive can't be listed; its message is the tool's answer after "Error: "."""


def _text(message: ToolMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return content
    return "".join(block.get("text", "") if isinstance(block, dict) else str(block) for block in content)


async def _call(tool: BaseTool, args: dict, config: RunnableConfig | None = None) -> tuple[bool, str]:
    """Call a server tool; (succeeded, its text). It inherits the run's callbacks unless `config` says otherwise."""
    message = await tool.ainvoke({
        "type": "tool_call",
        "id": f"call-{uuid.uuid4().hex}",
        "name": tool.name,
        "args": args,
    }, config)
    return message.status != "error", _text(message)


async def _listed(tool: BaseTool, args: dict, what: str) -> list[dict]:
    ok, text = await _call(tool, args)
    if not ok:
        raise ArchiveError(f"could not list {what}: {text}")
    return json.loads(text).get("value", [])


class InvoiceArchive:
    """The Invoice archive in the owner's one business drive, reached through the server's drive tools."""

    def __init__(self, tools: Mapping[str, BaseTool]):
        self._tools = tools
        self._drive_id: str | None = None

    async def drive_id(self) -> str:
        if self._drive_id is None:
            drives = await _listed(self._tools[LIST_DRIVES_TOOL], {}, "the OneDrive drives")
            business = [d for d in drives if d.get("driveType") == "business"]
            if len(business) != 1:
                raise ArchiveError(f"expected exactly one business OneDrive drive, found {len(business)}")
            self._drive_id = business[0]["id"]
        return self._drive_id

    async def children(self, item_id: str, what: str) -> list[dict]:
        return await _listed(self._tools[LIST_FOLDER_TOOL], {
            "driveId": await self.drive_id(),
            "driveItemId": item_id,
            "select": "id,name,size,folder,file",
            "fetchAllPages": True,
        }, what)

    async def subfolder(self, parent_id: str, name: str, parent_path: str) -> str | None:
        """The id of the folder `name` in the folder `parent_id`, matched case-insensitively, or None."""
        for item in await self.children(parent_id, parent_path or "the OneDrive root"):
            if "folder" in item and item.get("name", "").casefold() == name.casefold():
                return item["id"]
        return None

    async def admin_folder(self) -> str:
        """The id of `Documents/ittopia/admin`; an error if it is missing."""
        item_id, path = "root", ""
        for name in ARCHIVE_FOLDERS:
            found = await self.subfolder(item_id, name, path)
            path = f"{path}/{name}" if path else name
            if found is None:
                raise ArchiveError(f"the Invoice archive {ARCHIVE_PATH} was not found in OneDrive "
                                   f"(no folder {path}); it is never created by the agent")
            item_id = found
        return item_id


def _files(items: list[dict]) -> list[dict]:
    return sorted((i for i in items if "file" in i), key=lambda i: i.get("name", "").casefold())


def _month_order(name: str) -> tuple[int, str]:
    folded = [m.casefold() for m in MONTHS]
    return (folded.index(name.casefold()), "") if name.casefold() in folded else (len(MONTHS), name.casefold())


NAMES_ONLY = "Matched by file name only: the files' contents were not compared."


async def _list(tools: Mapping[str, BaseTool], year: int, month: int | None) -> str:
    if month is not None and not 1 <= month <= 12:
        return f"Error: month must be 1 to 12, not {month}."
    archive = InvoiceArchive(tools)
    admin = await archive.admin_folder()
    year_path = f"{ARCHIVE_PATH}/{year}"
    year_id = await archive.subfolder(admin, str(year), ARCHIVE_PATH)
    if month is None:
        if year_id is None:
            return f"The Invoice archive holds nothing for {year} (there is no folder {year_path})."
        months = sorted((i for i in await archive.children(year_id, year_path) if "folder" in i),
                        key=lambda i: _month_order(i["name"]))
        if not months:
            return f"The Invoice archive holds nothing for {year} ({year_path} has no month folders)."
        lines = [f"Invoice archive {year_path}, month folders and their files:"]
        for folder in months:
            names = [f["name"] for f in _files(await archive.children(folder["id"], f"{year_path}/{folder['name']}"))]
            lines.append(f"- {folder['name']}: {', '.join(names) if names else '(no files)'}")
        return "\n".join([*lines, NAMES_ONLY])
    month_name = MONTHS[month - 1]
    month_path = f"{year_path}/{month_name}"
    month_id = year_id and await archive.subfolder(year_id, month_name, year_path)
    if not month_id:
        return f"The Invoice archive holds nothing for {month_name} {year} (there is no folder {month_path})."
    found = _files(await archive.children(month_id, month_path))
    if not found:
        return f"The Invoice archive holds nothing for {month_name} {year} ({month_path} has no files)."
    lines = [f"Invoice archive {month_path}, {len(found)} file(s):"]
    lines += [f"- {f['name']} ({f.get('size', '?')} bytes)" for f in found]
    return "\n".join([*lines, NAMES_ONLY])


class ListInvoiceArchiveInput(BaseModel):
    year: int = Field(description="The year of the invoice dates, e.g. 2026.")
    month: int | None = Field(
        default=None,
        description="The month of the invoice dates, 1 to 12. Leave it out to list the whole year.",
    )


DESCRIPTION = """
List the Invoice archive in the owner's OneDrive
(Documents/ittopia/admin/<year>/<Month>/, where Processed Purchase
invoices are filed by the year and month of their invoice date).

With a month: the file names and sizes in that month's folder. Without a
month: the year's month folders and the file names in each.

It matches names only: it can't tell whether a file in Downloads is the
same invoice as one in the archive. When you answer from it, say that
only names were matched.

A missing year or month folder means the archive holds nothing there (not
an error). On failure returns a string beginning with "Error:".
""".strip()


def build_list_invoice_archive(name: str, tools: Mapping[str, BaseTool]) -> BaseTool:
    """The model-facing listing, over the server's list-drives and list-folder-files."""

    async def list_invoice_archive(year: int, month: int | None = None) -> str:
        if LIST_DRIVES_TOOL not in tools:
            return f"Error: the MS365 server has no {LIST_DRIVES_TOOL} tool."
        try:
            return await _list(tools, year, month)
        except TransientMcpError:
            raise  # the graph retries a read
        except ArchiveError as e:
            return f"Error: {e}"
        except Exception as e:
            return f"Error: {type(e).__name__}: {e}"

    return StructuredTool.from_function(
        coroutine=list_invoice_archive,
        name=name,
        description=DESCRIPTION,
        args_schema=ListInvoiceArchiveInput,
    )


LIST_INVOICE_ARCHIVE = ToolWrapper(
    name="list_invoice_archive",
    replaces=LIST_FOLDER_TOOL,
    build=build_list_invoice_archive,
    classification=READ,
)


# --- the Processed check ----------------------------------------------------------------------

MAX_FILE_BYTES = 25 * 1024 * 1024  # one PUT range (Graph allows 60 MiB per request)
PDF_MAGIC = b"%PDF-"
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


@dataclass(frozen=True)
class LocalPdf:
    """A local Purchase invoice that passed the local file rules."""

    path: Path
    name: str
    content: bytes


def downloads_root() -> Path:
    """The Downloads folder the Informer server checks: INFORMER_DOWNLOADS_DIR (also from `.env`), or ~/Downloads."""
    return Path(settings.informer_downloads_dir or Path.home() / "Downloads").expanduser().resolve()


def read_local_pdf(path: str) -> LocalPdf:
    """The file at `path` (relative to Downloads unless absolute) if it is a `.pdf` with the PDF magic,
    inside Downloads, and at most 25 MB; otherwise ArchiveError. Never calls a server."""
    if not path or not path.strip():
        raise ArchiveError("a path is required.")
    downloads = downloads_root()
    raw = Path(path).expanduser()
    if not raw.is_absolute():
        raw = downloads / raw
    try:
        resolved = raw.resolve(strict=True)
    except FileNotFoundError:
        raise ArchiveError(f"file not found: {path}") from None
    if not resolved.is_file():
        raise ArchiveError(f"not a file: {path}")
    if not resolved.is_relative_to(downloads):
        raise ArchiveError(f"the file must be inside the Downloads folder ({downloads}), not elsewhere.")
    if resolved.suffix.lower() != ".pdf":
        raise ArchiveError("only PDF files (.pdf) can be filed in the Invoice archive.")
    if resolved.stat().st_size > MAX_FILE_BYTES:  # refuse by size before reading the file
        raise ArchiveError("the file is over the 25 MB limit.")
    content = resolved.read_bytes()
    if len(content) > MAX_FILE_BYTES:  # it grew between the stat and the read
        raise ArchiveError("the file is over the 25 MB limit.")
    if not content.startswith(PDF_MAGIC):
        raise ArchiveError("the file's contents are not a PDF.")
    return LocalPdf(path=resolved, name=resolved.name, content=content)


def month_of(invoice_date: str) -> tuple[int, str]:
    """(year, English month name) of a `YYYY-MM-DD` invoice date; otherwise ArchiveError."""
    try:
        if not _ISO_DATE.fullmatch(invoice_date):
            raise ValueError
        parsed = date.fromisoformat(invoice_date)
    except ValueError:
        raise ArchiveError(f"invoice_date must be a date written YYYY-MM-DD, not {invoice_date!r}.") from None
    return parsed.year, MONTHS[parsed.month - 1]


def renamed(name: str, taken: set[str]) -> str:
    """`name`, or the name OneDrive's rename gives it when taken (`<stem> 1<ext>`, `<stem> 2<ext>`, …).
    `taken` holds casefolded names: OneDrive matches names case-insensitively."""
    if name.casefold() not in taken:
        return name
    stem, suffix = Path(name).stem, Path(name).suffix
    number = 1
    while f"{stem} {number}{suffix}".casefold() in taken:
        number += 1
    return f"{stem} {number}{suffix}"


@dataclass(frozen=True)
class ArchiveCheck:
    """Where a local PDF stands against the month folder of its invoice date."""

    month_path: str  # Documents/ittopia/admin/<year>/<Month>
    admin_id: str
    year_id: str | None  # None: the year folder is missing
    month_id: str | None  # None: the month folder is missing
    archived_as: str | None  # the archive path of the same contents, if they are there (Processed)
    target_path: str  # where an Upload to OneDrive would put the file
    renamed: bool  # a different file has the name, so OneDrive's rename gives the target its name


async def check_archive(tools: Mapping[str, BaseTool], pdf: LocalPdf, invoice_date: str,
                        archive: InvoiceArchive | None = None) -> ArchiveCheck:
    """Compare `pdf`'s quickXorHash with each file's in the invoice date's month folder (never downloading)."""
    year, month = month_of(invoice_date)
    archive = archive or InvoiceArchive(tools)
    admin = await archive.admin_folder()
    year_path = f"{ARCHIVE_PATH}/{year}"
    month_path = f"{year_path}/{month}"
    year_id = await archive.subfolder(admin, str(year), ARCHIVE_PATH)
    month_id = await archive.subfolder(year_id, month, year_path) if year_id else None
    items = await archive.children(month_id, month_path) if month_id else []
    digest = quick_xor_hash(pdf.content)
    archived_as = next((f"{month_path}/{f['name']}" for f in _files(items)
                        if f["file"].get("hashes", {}).get("quickXorHash") == digest), None)
    name = renamed(pdf.name, {i.get("name", "").casefold() for i in items})
    return ArchiveCheck(month_path=month_path, admin_id=admin, year_id=year_id, month_id=month_id,
                        archived_as=archived_as, target_path=f"{month_path}/{name}", renamed=name != pdf.name)


def _check_answer(pdf: LocalPdf, check: ArchiveCheck) -> str:
    if check.archived_as:
        return (f"Processed: these contents are already in the Invoice archive as {check.archived_as} "
                f"(Uploaded to OneDrive).")
    lines = [f"Not Processed: these contents are not in {check.month_path}.",
             f"Target path: {check.target_path}"]
    if check.renamed:
        lines.append(f"A different file is already named {pdf.name} there, so OneDrive will rename this one "
                     f"as above (the upload's result gives the final name).")
    return "\n".join(lines)


class CheckInvoiceArchiveInput(BaseModel):
    path: str = Field(description="The local PDF, inside the Downloads folder (absolute, or relative to Downloads).")
    invoice_date: str = Field(description="The invoice date printed on the invoice, YYYY-MM-DD.")


CHECK_DESCRIPTION = """
The Processed check: is this local Purchase invoice PDF already in the
Invoice archive in the owner's OneDrive? It compares the file's contents
(OneDrive's quickXorHash) with each file in the archive folder of the
invoice date's year and month (Documents/ittopia/admin/<year>/<Month>/),
never by name, so a renamed copy is found and a different file with the
same name is not mistaken for it.

invoice_date is the date printed on the invoice (read it with
read_pdf_text), YYYY-MM-DD. The file must be a PDF inside the Downloads
folder, at most 25 MB.

Answers either "Processed: ..." with the archive path of the matching
file, or "Not Processed: ..." with the "Target path:" an Upload to
OneDrive would use (pass it unchanged to the upload). When a different
file already has the name, the target path carries OneDrive's rename and
a line says so. On failure returns a string beginning with "Error:".
""".strip()


def build_check_invoice_archive(name: str, tools: Mapping[str, BaseTool]) -> BaseTool:
    """The model-facing Processed check, over the server's list-drives and list-folder-files."""

    async def check_invoice_archive(path: str, invoice_date: str) -> str:
        try:
            pdf = read_local_pdf(path)
            month_of(invoice_date)  # refuse a bad date before calling the server
            if LIST_DRIVES_TOOL not in tools:
                return f"Error: the MS365 server has no {LIST_DRIVES_TOOL} tool."
            return _check_answer(pdf, await check_archive(tools, pdf, invoice_date))
        except TransientMcpError:
            raise  # the graph retries a read
        except ArchiveError as e:
            return f"Error: {e}"
        except Exception as e:
            return f"Error: {type(e).__name__}: {e}"

    return StructuredTool.from_function(
        coroutine=check_invoice_archive,
        name=name,
        description=CHECK_DESCRIPTION,
        args_schema=CheckInvoiceArchiveInput,
    )


CHECK_INVOICE_ARCHIVE = ToolWrapper(
    name="check_invoice_archive",
    replaces=LIST_FOLDER_TOOL,
    build=build_check_invoice_archive,
    classification=READ,
)


# --- the Upload to OneDrive -------------------------------------------------------------------

CREATE_FOLDER_TOOL = "create-onedrive-folder"
UPLOAD_SESSION_TOOL = "create-upload-session"
UPLOAD_TIMEOUT = httpx.Timeout(300.0, connect=30.0)  # one range of up to 25 MB

# PUTs a file's bytes, whole, to an upload session's `uploadUrl` and returns the created driveItem,
# or raises an exception whose text never names the uploadUrl: `httpx_put` against OneDrive, the
# Fixture world's own (fixture_world.ms365.put_upload_session) against its stand-in's sessions.
PutToSession = Callable[[str, bytes], Awaitable[dict]]


class UploadFailed(Exception):
    """The PUT to an upload session failed; the message never names the uploadUrl."""


class _HideUrls(logging.Filter):
    """Drops log records naming an uploadUrl in use (httpx logs every request's URL at INFO)."""

    def __init__(self):
        super().__init__()
        self.urls: set[str] = set()

    def filter(self, record: logging.LogRecord) -> bool:
        return not self.urls or not any(url in record.getMessage() for url in self.urls)


_HIDDEN = _HideUrls()
logging.getLogger("httpx").addFilter(_HIDDEN)


def _graph_error_text(response: httpx.Response) -> str:
    try:
        error = response.json().get("error") or {}
        detail = f": {error.get('code')} ({error.get('message')})" if isinstance(error, dict) and error else ""
    except ValueError:
        detail = ""
    return f"OneDrive answered {response.status_code} {response.reason_phrase}{detail}"


async def httpx_put(upload_url: str, content: bytes, *, transport: httpx.AsyncBaseTransport | None = None) -> dict:
    """The PUT to OneDrive: the whole file in one range (`Content-Length`, `Content-Range`), with no
    `Authorization` header (the uploadUrl is pre-authenticated). On failure the session is deleted,
    best effort, and UploadFailed is raised without the URL, the httpx error or its cause."""
    size = len(content)
    hidden = {upload_url, str(httpx.URL(upload_url))}  # as given, and as httpx writes it in its log line
    _HIDDEN.urls.update(hidden)
    try:
        async with httpx.AsyncClient(transport=transport, timeout=UPLOAD_TIMEOUT) as client:
            try:
                response = await client.put(upload_url, content=content, headers={
                    "Content-Length": str(size),
                    "Content-Range": f"bytes 0-{size - 1}/{size}",
                })
                failure = None if response.status_code in (200, 201) else _graph_error_text(response)
            except httpx.HTTPError as e:
                failure = f"the PUT did not complete ({type(e).__name__})"
            if failure is None:
                return response.json()
            try:
                await client.delete(upload_url)
            except httpx.HTTPError:
                pass  # best effort: an unfinished session expires on its own
    finally:
        _HIDDEN.urls.difference_update(hidden)
    raise UploadFailed(failure)


async def _created_folder(archive: InvoiceArchive, tools: Mapping[str, BaseTool], parent_id: str, name: str,
                          parent_path: str) -> str:
    """The id of a new folder `name` in `parent_id`; one created meanwhile (a conflict) is listed again."""
    ok, text = await _call(tools[CREATE_FOLDER_TOOL], {
        "driveId": await archive.drive_id(),
        "driveItemId": parent_id,
        "body": {"name": name, "folder": {}, "@microsoft.graph.conflictBehavior": "fail"},
    })
    if ok:
        return json.loads(text)["id"]
    if "nameAlreadyExists" in text:
        found = await archive.subfolder(parent_id, name, parent_path)
        if found:
            return found
    raise ArchiveError(f"could not create the folder {parent_path}/{name}; nothing was uploaded: {text}")


async def _upload(tools: Mapping[str, BaseTool], put: PutToSession, path: str, invoice_date: str,
                  target_path: str) -> str:
    pdf = read_local_pdf(path)
    year, month = month_of(invoice_date)
    for needed in (LIST_DRIVES_TOOL, CREATE_FOLDER_TOOL, UPLOAD_SESSION_TOOL):
        if needed not in tools:
            return f"Error: the MS365 server has no {needed} tool."
    archive = InvoiceArchive(tools)
    check = await check_archive(tools, pdf, invoice_date, archive)
    if check.archived_as:
        return (f"NOT UPLOADED: these contents were already Uploaded to OneDrive as {check.archived_as}.\n"
                f"Nothing was uploaded.")
    if target_path != check.target_path:
        return (f"Error: target_path {target_path!r} is not where this file would go now ({check.target_path}): "
                f"the Invoice archive folder changed, or the path was not taken from the Processed check. "
                f"Nothing was uploaded. Run the Processed check (ms365_check_invoice_archive) again and pass "
                f"its Target path unchanged.")
    year_path = f"{ARCHIVE_PATH}/{year}"
    year_id = check.year_id or await _created_folder(archive, tools, check.admin_id, str(year), ARCHIVE_PATH)
    month_id = check.month_id or await _created_folder(archive, tools, year_id, month, year_path)
    # No callbacks: the session's result carries the uploadUrl, a bearer capability, which a callback
    # inherited from the run (Langfuse) would otherwise trace with the call's output.
    ok, text = await _call(tools[UPLOAD_SESSION_TOOL], {
        "driveId": await archive.drive_id(),
        "driveItemId": f"{month_id}:/{pdf.name}:",
        # Only the conflict behaviour: Graph refuses `name` here with 400 (ticket 02's probe).
        "body": {"item": {"@microsoft.graph.conflictBehavior": "rename"}},
    }, {"callbacks": []})
    if not ok:
        return f"Error: could not start the upload of {pdf.name} to {check.month_path}; nothing was uploaded: {text}"
    upload_url = json.loads(text).get("uploadUrl")
    if not upload_url:
        return f"Error: OneDrive started no upload session for {pdf.name}; nothing was uploaded."
    try:
        item = await put(upload_url, pdf.content)
    except Exception as e:
        detail = str(e).replace(upload_url, "<uploadUrl>") or type(e).__name__
        return f"Error: the upload of {pdf.name} to {check.month_path} failed: {detail}"
    # The name OneDrive reports wins over the predicted one: an unfinished session also holds a name.
    name = item.get("name") or pdf.name
    lines = [f"Uploaded to OneDrive: {check.month_path}/{name} ({item.get('size', len(pdf.content))} bytes)."]
    if name != pdf.name:
        lines.append(f"OneDrive gave it this name because the name {pdf.name} is already taken there.")
    return "\n".join(lines)


class UploadToOneDriveInput(BaseModel):
    path: str = Field(description="The local PDF, inside the Downloads folder (absolute, or relative to Downloads).")
    invoice_date: str = Field(description="The invoice date printed on the invoice, YYYY-MM-DD.")
    target_path: str = Field(
        description=(
            "The Target path the Processed check (ms365_check_invoice_archive) gave for this file, "
            "unchanged, e.g. Documents/ittopia/admin/2026/October/kpn-factuur-123456.pdf. "
            "The upload is refused if it doesn't match."
        )
    )


UPLOAD_DESCRIPTION = """
Upload to OneDrive: put a local Purchase invoice PDF in the Invoice
archive in the owner's OneDrive, in the folder of its invoice date's
year and month (Documents/ittopia/admin/<year>/<Month>/), under its own
file name. A missing year or month folder is created. Nothing in
OneDrive is ever overwritten: when the name is taken, OneDrive renames
this file (e.g. "Factuur 1.pdf").

Run the Processed check (ms365_check_invoice_archive) first and pass its
Target path unchanged as target_path; invoice_date is the date printed
on the invoice (read it with read_pdf_text), YYYY-MM-DD. The file must
be a PDF inside the Downloads folder, at most 25 MB.

This tool requires human approval before execution (it is a Write action).

On success returns the archive path OneDrive gave the file and its size.
If the same contents are already in the month folder, nothing is
uploaded and the first line begins with "NOT UPLOADED:"; start your
answer with that line, on its own line and in capitals, so the owner
sees that nothing was uploaded.
On failure returns a string beginning with "Error:".
""".strip()


def build_upload_to_onedrive(put: PutToSession) -> Callable[[str, Mapping[str, BaseTool]], BaseTool]:
    """The model-facing Upload to OneDrive builder, over the server's drive tools, `put` sending the bytes."""

    def build(name: str, tools: Mapping[str, BaseTool]) -> BaseTool:
        async def upload_to_onedrive(path: str, invoice_date: str, target_path: str) -> str:
            try:
                return await _upload(tools, put, path, invoice_date, target_path)
            except TransientMcpError as e:  # a Write action is never retried: reported, not raised
                return f"Error: OneDrive is temporarily unavailable; nothing was uploaded ({e})"
            except ArchiveError as e:
                return f"Error: {e}"
            except Exception as e:
                return f"Error: {type(e).__name__}: {e}"

        return StructuredTool.from_function(
            coroutine=upload_to_onedrive,
            name=name,
            description=UPLOAD_DESCRIPTION,
            args_schema=UploadToOneDriveInput,
        )

    return build


def upload_to_onedrive(put: PutToSession) -> ToolWrapper:
    """The Upload to OneDrive (a Write action), bound in place of create-upload-session."""
    return ToolWrapper(name="upload_to_onedrive", replaces=UPLOAD_SESSION_TOOL, build=build_upload_to_onedrive(put))
