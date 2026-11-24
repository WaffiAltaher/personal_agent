# 09: Docs and setup wizard for the Invoice archive

**Type:** task

**What to build:** `CLAUDE.md` says the MS365 server now also reaches the Invoice archive through three agent-side tools, that its drive tools are enabled but never bound, that `read_pdf_text` exists. The setup wizard's Azure app stage (`scripts/setup_wizard.sh`) adds delegated `Files.ReadWrite` to the permissions it lists, so a fresh setup grants it. The `src/agent/tools/ms365_mcp.py` docstring names the scopes the server now requests.

**Blocked by:** 05, 06

**Status:** ready-for-agent

- [ ] `CLAUDE.md` describes the archive tools, and the PDF text tool
- [ ] The wizard's Azure stage lists `Files.ReadWrite` (delegated), and its tests cover it
- [ ] The full suite passes (`uv run pytest -m "not live and not browser"`)

Spec: `../spec.md` (Route and login). ADR-020.

## Comments
