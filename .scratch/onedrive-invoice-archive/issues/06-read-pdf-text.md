# 06: `read_pdf_text` reads a local PDF's text for the invoice date

**Type:** task

**What to build:** A new local tool `read_pdf_text(path)`, in `src/agent/tools/`, wrapped in `read_tool(...)` in `LOCAL_TOOLS`. It returns the text of the PDF's first pages, capped like `read_file`, and `Error: ...` for a missing file, a non-PDF or an unreadable one. A PDF with no extractable text answers that it has no text layer, probably a scan, and that the agent must ask the owner for the invoice date. It uses `pypdf` (new dependency in `pyproject.toml`). An eval stand-in in `EVAL_FILE_STAND_INS` (`src/agent/evals/harness.py`, beside `fixture_read_file`) confines paths to `FIXTURE_WORLD_FILES_ROOT`, the run's Downloads folder, as `fixture_read_file` does. The eval Downloads gain a seeded text PDF with a printed invoice date and a PDF with no text layer.

**Blocked by:** None (can start immediately)

**Status:** resolved

- [x] A seeded text PDF returns text containing its invoice date
- [x] A PDF with no text layer returns the "no text layer, ask the owner for the invoice date" answer, not an error
- [x] A non-PDF and a missing file give `Error:` lines
- [x] The stand-in refuses a path outside the files root as not found
- [x] The tool is classified read
- [x] The full suite passes (`uv run pytest -m "not live and not browser"`)

Spec: `../spec.md` (Reading the invoice date). ADR-020.

## Comments

- Built `read_pdf_text` in `src/agent/tools/pdf_text.py` (pypdf 7.1.1): text of the first 3 pages, capped at 20,000 characters (files up to 25 MB, the Upload to OneDrive limit); `Error:` for missing, non-PDF (no `%PDF-` magic), password-protected or damaged files; the `NO_TEXT_LAYER` answer for a scan. `read_tool(...)` in `LOCAL_TOOLS`; the eval stand-in `fixture_read_pdf_text` is in `EVAL_FILE_STAND_INS`. `src/fixture_world/pdfs.py` builds one-page PDFs (`text_pdf(lines)`, `no_text_pdf()`); the eval Downloads gain `kpn-factuur-123456.pdf` (printed `Factuurdatum: 14-10-2026`) and `scan-factuur.pdf` (no text layer). Tests: `tests/test_read_pdf_text.py`.
