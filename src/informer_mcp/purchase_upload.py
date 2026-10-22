# src/informer_mcp/purchase_upload.py
"""Purchase invoice PDF check and upload (ADR-012)."""

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Protocol

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from informer_mcp.config import InformerSettings

READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True)
PDF_MAGIC = b"%PDF-"


class PurchaseInvoiceHandover(Protocol):
    async def hand_over(self, file_name: str, content: bytes) -> None:
        """Send one Purchase invoice PDF to Informer."""


@dataclass(frozen=True)
class ValidatedPurchaseInvoice:
    path: Path
    file_name: str
    folder: str
    size: int
    content: bytes


def downloads_root(settings: InformerSettings) -> Path:
    root = settings.downloads_dir or (Path.home() / "Downloads")
    return root.expanduser().resolve()


def upload_log_path(settings: InformerSettings) -> Path:
    return (settings.purchase_upload_log or Path.home() / ".informer_mcp" / "purchase-uploads.jsonl").expanduser()


def fingerprint(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def earlier_upload_date(settings: InformerSettings, content: bytes) -> str | None:
    """The date of the first logged hand-over of these contents (under any name), if any."""
    try:
        lines = upload_log_path(settings).read_text().splitlines()
    except FileNotFoundError:
        return None
    wanted = fingerprint(content)
    for line in lines:
        try:
            entry = json.loads(line)
        except ValueError:
            continue  # a torn or foreign line must not hide the others
        if entry.get("fingerprint") == wanted:
            return entry["date"]
    return None


def record_upload(settings: InformerSettings, content: bytes) -> None:
    path = upload_log_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {"fingerprint": fingerprint(content), "date": (settings.today or date.today()).isoformat()}
    with open(path, "a") as log:
        log.write(json.dumps(entry) + "\n")


def _describe_size(size: int) -> str:
    return f"{size / (1024 * 1024):g} MB" if size >= 1024 * 1024 else f"{size} bytes"


def validate_purchase_invoice_path(path_str: str, settings: InformerSettings) -> ValidatedPurchaseInvoice:
    """Shared checks for check and upload. Raises ValueError with a refusal reason."""
    if not path_str or not str(path_str).strip():
        raise ValueError("Path is required.")

    downloads = downloads_root(settings)
    raw = Path(path_str).expanduser()
    if not raw.is_absolute():
        raw = downloads / raw

    try:
        resolved = raw.resolve(strict=True)
    except FileNotFoundError as exc:
        raise ValueError(f"File not found: {path_str}") from exc

    if not resolved.is_file():
        raise ValueError(f"Not a file: {path_str}")

    try:
        resolved.relative_to(downloads)
    except ValueError as exc:
        raise ValueError(
            f"Path must be inside the Downloads folder ({downloads}), not elsewhere."
        ) from exc

    if resolved.suffix.lower() != ".pdf":
        raise ValueError("Only PDF files (.pdf extension) are accepted.")

    cap = settings.purchase_upload_max_bytes
    if resolved.stat().st_size > cap:  # refuse by size before loading the file
        raise ValueError(f"File exceeds the size cap ({_describe_size(cap)}).")
    content = resolved.read_bytes()
    if len(content) > cap:  # it grew between the stat and the read
        raise ValueError(f"File exceeds the size cap ({_describe_size(cap)}).")

    if not content.startswith(PDF_MAGIC):
        raise ValueError("File content is not a PDF.")

    return ValidatedPurchaseInvoice(
        path=resolved,
        file_name=resolved.name,
        folder=str(resolved.parent),
        size=len(content),
        content=content,
    )


def register_purchase_upload_tools(
    mcp: FastMCP,
    settings: InformerSettings,
    handover: PurchaseInvoiceHandover,
) -> None:
    @mcp.tool(annotations=READ_ONLY)
    async def check_purchase_invoice(path: str) -> dict:
        """Check a Purchase invoice PDF before proposing an upload. Call this first and tell
        the owner what you found: either why the file is refused, or its name, folder and size.
        If it says the same contents were already uploaded on a date, tell the owner and ask
        the owner before proposing to upload it again."""
        validated = validate_purchase_invoice_path(path, settings)
        result = {
            "file_name": validated.file_name,
            "folder": validated.folder,
            "size": validated.size,
        }
        if earlier := earlier_upload_date(settings, validated.content):
            result["already_uploaded_on"] = earlier
            result["warning"] = f"already uploaded on {earlier}"
        return result

    @mcp.tool()
    async def upload_purchase_invoice(path: str, allow_duplicate: bool = False) -> dict:
        """Upload a Purchase invoice PDF for the accountant to book. Re-runs every check,
        then sends only the file (no invoice details). Needs owner Approval.
        Contents already uploaded before (under any name) are refused with the earlier date.
        Ask the owner before re-uploading: set `allow_duplicate` to true only when the owner
        has said they want it uploaded again; never set it on your own."""
        validated = validate_purchase_invoice_path(path, settings)
        if not allow_duplicate and (earlier := earlier_upload_date(settings, validated.content)):
            raise ValueError(
                f"Refused: these contents were already uploaded on {earlier}. Ask the owner; "
                "only if they want it uploaded again, retry with allow_duplicate set to true."
            )
        try:
            await handover.hand_over(validated.file_name, validated.content)
        except Exception as exc:
            raise ValueError(str(exc)) from exc
        record_upload(settings, validated.content)
        return {
            "file_name": validated.file_name,
            "folder": validated.folder,
            "size": validated.size,
            "message": f"Uploaded {validated.file_name} for booking.",
        }
