# 09: Docs and setup wizard for the Invoice archive

**Type:** task

**What to build:** `CLAUDE.md` says the MS365 server now also reaches the Invoice archive through three agent-side tools, that its drive tools are enabled but never bound, that `read_pdf_text` exists. The setup wizard's Azure app stage (`scripts/setup_wizard.sh`) adds delegated `Files.ReadWrite` to the permissions it lists, so a fresh setup grants it. The `src/agent/tools/ms365_mcp.py` docstring names the scopes the server now requests.

**Blocked by:** 05, 06

**Status:** resolved

- [x] `CLAUDE.md` describes the archive tools, and the PDF text tool
- [x] The wizard's Azure stage lists `Files.ReadWrite` (delegated), and its tests cover it
- [x] The full suite passes (`uv run pytest -m "not live and not browser"`)

Spec: `../spec.md` (Route and login). ADR-020.

## Comments

- 2026-11-24: Done. `CLAUDE.md`: Microsoft 365 reaches the OneDrive Invoice archive; the tools paragraph names `read_pdf_text` and the three archive tools over the never-bound drive tools (ADR-020); the config paragraph says the agent also reads `INFORMER_DOWNLOADS_DIR`. The wizard's Azure app stage adds delegated `Files.ReadWrite` (not `.All`) and checks it in `--list-permissions`; no re-login step, as the owner decided. `ms365_mcp.py`'s docstring names the scopes the server requests with `ENABLED_TOOLS` (read from the pinned 0.159.1 `endpoints.json`). Test: `test_the_azure_stage_adds_files_readwrite_for_the_invoice_archive` in `tests/test_setup_wizard.py`.
