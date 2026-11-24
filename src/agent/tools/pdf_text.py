"""read_pdf_text: the text of a local PDF's first pages, so the model can read a Purchase
invoice's invoice date (spec: Reading the invoice date; ADR-020). A read: it changes nothing."""

from pathlib import Path

from langchain_core.tools import StructuredTool, tool
from pydantic import BaseModel, Field
from pypdf import PdfReader

from agent.tools.filesystem import inside_files_root

PDF_MAGIC = b"%PDF-"  # the first bytes of every PDF; the Invoice archive's file rules use it too
MAX_PAGES = 3  # an invoice date is printed on the first page; the next ones only add context
MAX_BYTES = 25 * 1024 * 1024  # the largest PDF an Upload to OneDrive takes
MAX_CHARS = 20_000  # the text handed back, like read_file's cap on what enters the context

NO_TEXT_LAYER = (
    "This PDF has no text layer (it is probably a scan), so its invoice date can't be read. "
    "Do not guess it: ask the owner for the invoice date."
)


class ReadPdfTextInput(BaseModel):
    path: str = Field(description="Absolute or relative path to the local PDF file to read.")


@tool("read_pdf_text", args_schema=ReadPdfTextInput)
def read_pdf_text(path: str) -> str:
    """
    Read the text of a local PDF's first pages (at most 3), for example to find the invoice
    date printed on a Purchase invoice before uploading it.

    If the PDF has no text layer (a scan), the result says so: then ask the owner for the
    invoice date instead of guessing it. On failure (missing file, not a PDF, unreadable or
    too large) the tool returns a string beginning with "Error:" instead of raising.
    """
    try:
        file_path = Path(path).expanduser().resolve()
        if not file_path.exists():
            return f"Error: file not found: {file_path}"
        if not file_path.is_file():
            return f"Error: path exists but is not a file: {file_path}"
        size = file_path.stat().st_size
        if size > MAX_BYTES:
            return f"Error: file is too large to read ({size:,} bytes). Maximum allowed is {MAX_BYTES:,} bytes."
        with file_path.open("rb") as f:
            if f.read(len(PDF_MAGIC)) != PDF_MAGIC:
                return f"Error: not a PDF: {file_path}"
        reader = PdfReader(file_path)
        if reader.is_encrypted and not reader.decrypt(""):
            return f"Error: the PDF is password-protected: {file_path}"
        pages = reader.pages[:MAX_PAGES]
        text = "\n\n".join((page.extract_text() or "").strip() for page in pages).strip()
        if not text:
            return NO_TEXT_LAYER
        if len(text) > MAX_CHARS:
            text = text[:MAX_CHARS] + f"\n\n[cut off after {MAX_CHARS:,} characters]"
        return text
    except PermissionError:
        return f"Error: permission denied reading {path}"
    except Exception as e:
        # Broad catch is intentional: a damaged PDF must give the agent a ToolMessage, not a traceback.
        return f"Error: could not read the PDF {path}: {type(e).__name__}: {e}"


# --- Eval stand-in ---
# Same name, arguments and description, confined to the files root (an eval run's Downloads
# folder) like fixture_read_file: a path outside it is reported as not found.

def _read_fixture_pdf_text(path: str) -> str:
    resolved = inside_files_root(path)
    if resolved is None:
        return f"Error: file not found: {Path(path).expanduser()}"
    return read_pdf_text.func(str(resolved))


fixture_read_pdf_text = StructuredTool.from_function(
    func=_read_fixture_pdf_text,
    name=read_pdf_text.name,
    description=read_pdf_text.description,
    args_schema=ReadPdfTextInput,
)
