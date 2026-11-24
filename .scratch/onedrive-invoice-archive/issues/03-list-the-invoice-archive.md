# 03: List the Invoice archive through a read wrapper over the stand-in's drive tools

**Type:** task

**What to build:** The first slice end to end: the owner asks "which October 2026 invoices are in the Invoice archive?" and the agent answers from the Invoice archive.
- `ToolWrapper` gains a classification (read or Write action, default Write action); the loader binds a read wrapper with `read_tool(...)` instead of `write_action(...)`.
- `ENABLED_TOOLS` in `src/agent/tools/ms365_mcp.py` gains `list-drives` and `list-folder-files` (the rest come with tickets 04 and 05); neither joins `EXPOSED_TOOLS` or `READ_TOOLS`.
- A new module (beside `ms365_attachments.py`) holds the archive lookup (the single `business` drive from `list-drives`; `ittopia` → `admin` → year → month by id with `list-folder-files` from `root`, names matched case-insensitively; month names from a fixed English list) and the read wrapper `ms365_list_invoice_archive(year, month=None)`, added to `_TOOL_POLICY`'s wrappers. It returns names and sizes in a month's folder, or a year's month folders and their file names; a missing year or month answers that the Invoice archive holds nothing there; a missing `Documents/ittopia/admin` is an error. The description says it matches names only.
- The MS365 stand-in (`fixture_world.ms365`) gains `list-drives` and `list-folder-files` with the pinned server's argument shapes (`driveId`, `driveItemId`, OData options without `$`), over a drive directory named by `FIXTURE_WORLD_MS365_DRIVE`, seeded from `src/fixture_world/data/ms365/drive/` (an `Documents/ittopia/admin/2026/<Month>/` tree with a few Purchase invoice PDFs). Items get stable ids. The existing failure modes apply.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] The stand-in's argument shapes match the pinned server's listing: check them against the real server's tool listing, not from memory
- [ ] Through `load_all_tools(fixtures=True)`: `ms365_list_invoice_archive` is bound and classified read; `ms365_list-drives` and `ms365_list-folder-files` are not bound
- [ ] Listing a seeded month returns its file names; a missing month says the Invoice archive holds nothing there; a missing `Documents/ittopia/admin` is an `Error:` line
- [ ] The stand-in's logged-out mode gives a result naming the login command
- [ ] A wrapper with no classification is still a Write action (a test pins the default)
- [ ] The full suite passes (`uv run pytest -m "not live and not browser"`)

Spec: `../spec.md` (Loader; The Invoice archive tools; Fixture world and evals). ADR-020.

## Comments
