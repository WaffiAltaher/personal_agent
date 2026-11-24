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

Locating the archive: the drive is the single `business` drive from `list-drives`; folders are
found level by level by id with `list-folder-files`, starting at `root`, names matched
case-insensitively, as OneDrive matches them. A missing `Documents/ittopia/admin` is an error
(it is never created); a missing year or month means the archive holds nothing there.

Every refusal or failure is a string starting with "Error:". A transient failure is raised, so
the graph retries the read.
"""

import json
import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from langchain_core.messages import ToolMessage
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


async def _call(tool: BaseTool, args: dict) -> tuple[bool, str]:
    """Call a server tool; (succeeded, its text)."""
    message = await tool.ainvoke({
        "type": "tool_call",
        "id": f"call-{uuid.uuid4().hex}",
        "name": tool.name,
        "args": args,
    })
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


async def check_archive(tools: Mapping[str, BaseTool], pdf: LocalPdf, invoice_date: str) -> ArchiveCheck:
    """Compare `pdf`'s quickXorHash with each file's in the invoice date's month folder (never downloading)."""
    year, month = month_of(invoice_date)
    archive = InvoiceArchive(tools)
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
