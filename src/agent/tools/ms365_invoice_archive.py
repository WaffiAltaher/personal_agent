# src/agent/tools/ms365_invoice_archive.py
"""
The Invoice archive (`Documents/ittopia/admin/<year>/<Month>/` in the owner's OneDrive, ADR-020).

Agent-side tools over the MS365 server's drive tools, which are enabled but never bound, so the
model reaches only the Invoice archive and never a drive or item id:
- `ms365_list_invoice_archive(year, month=None)` (read): the names and sizes in a month's folder,
  or a year's month folders and their file names. It matches names only.

Locating the archive: the drive is the single `business` drive from `list-drives`; folders are
found level by level by id with `list-folder-files`, starting at `root`, names matched
case-insensitively, as OneDrive matches them. A missing `Documents/ittopia/admin` is an error
(it is never created); a missing year or month means the archive holds nothing there.

Every refusal or failure is a string starting with "Error:". A transient failure is raised, so
the graph retries the read.
"""

import json
import uuid
from collections.abc import Mapping

from langchain_core.messages import ToolMessage
from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field

from agent.tools.classification import READ
from agent.tools.mcp_loader import ToolWrapper, TransientMcpError

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
