# 06: `read_pdf_text` reads a local PDF's text for the invoice date

**Type:** task

**What to build:** A new local tool `read_pdf_text(path)`, in `src/agent/tools/`, wrapped in `read_tool(...)` in `LOCAL_TOOLS`. It returns the text of the PDF's first pages, capped like `read_file`, and `Error: ...` for a missing file, a non-PDF or an unreadable one. A PDF with no extractable text answers that it has no text layer, probably a scan, and that the agent must ask the owner for the invoice date. It uses `pypdf` (new dependency in `pyproject.toml`). An eval stand-in in `EVAL_FILE_STAND_INS` (`src/agent/evals/harness.py`, beside `fixture_read_file`) confines paths to `FIXTURE_WORLD_FILES_ROOT`, the run's Downloads folder, as `fixture_read_file` does. The eval Downloads gain a seeded text PDF with a printed invoice date and a PDF with no text layer.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] A seeded text PDF returns text containing its invoice date
- [ ] A PDF with no text layer returns the "no text layer, ask the owner for the invoice date" answer, not an error
- [ ] A non-PDF and a missing file give `Error:` lines
- [ ] The stand-in refuses a path outside the files root as not found
- [ ] The tool is classified read
- [ ] The full suite passes (`uv run pytest -m "not live and not browser"`)

Spec: `../spec.md` (Reading the invoice date). ADR-020.

## Comments
