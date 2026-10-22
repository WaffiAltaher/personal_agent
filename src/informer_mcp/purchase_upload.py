# src/informer_mcp/purchase_upload.py
"""Purchase invoice PDF check and upload (ADR-012)."""

from dataclasses import dataclass
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


def validate_purchase_invoice_path(path_str: str, settings: InformerSettings) -> ValidatedPurchaseInvoice:
    """Shared checks for check and upload. Raises ValueError with a refusal reason."""
    if not path_str or not str(path_str).strip():
        raise ValueError("Path is required.")

    raw = Path(path_str).expanduser()
    if not raw.is_absolute():
        raw = Path.cwd() / raw

    try:
        resolved = raw.resolve(strict=True)
    except FileNotFoundError as exc:
        raise ValueError(f"File not found: {path_str}") from exc

    if not resolved.is_file():
        raise ValueError(f"Not a file: {path_str}")

    downloads = downloads_root(settings)
    try:
        resolved.relative_to(downloads)
    except ValueError as exc:
        raise ValueError(
            f"Path must be inside the Downloads folder ({downloads}), not elsewhere."
        ) from exc

    if resolved.suffix.lower() != ".pdf":
        raise ValueError("Only PDF files (.pdf extension) are accepted.")

    content = resolved.read_bytes()
    if len(content) > settings.purchase_upload_max_bytes:
        cap_mb = settings.purchase_upload_max_bytes / (1024 * 1024)
        raise ValueError(f"File exceeds the size cap ({cap_mb:g} MB).")

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
        the owner what you found: either why the file is refused, or its name, folder and size."""
        validated = validate_purchase_invoice_path(path, settings)
        return {
            "file_name": validated.file_name,
            "folder": validated.folder,
            "size": validated.size,
        }

    @mcp.tool()
    async def upload_purchase_invoice(path: str) -> dict:
        """Upload a Purchase invoice PDF for the accountant to book. Re-runs every check,
        then sends only the file (no invoice details). Needs owner Approval."""
        validated = validate_purchase_invoice_path(path, settings)
        try:
            await handover.hand_over(validated.file_name, validated.content)
        except Exception as exc:
            raise ValueError(str(exc)) from exc
        return {
            "file_name": validated.file_name,
            "folder": validated.folder,
            "size": validated.size,
            "message": f"Uploaded {validated.file_name} for booking.",
        }
