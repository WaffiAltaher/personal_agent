# 03: List the Invoice archive through a read wrapper over the stand-in's drive tools

**Type:** task

**What to build:** The first slice end to end: the owner asks "which October 2026 invoices are in the Invoice archive?" and the agent answers from the Invoice archive.
- `ToolWrapper` gains a classification (read or Write action, default Write action); the loader binds a read wrapper with `read_tool(...)` instead of `write_action(...)`.
- `ENABLED_TOOLS` in `src/agent/tools/ms365_mcp.py` gains `list-drives` and `list-folder-files` (the rest come with tickets 04 and 05); neither joins `EXPOSED_TOOLS` or `READ_TOOLS`.
- A new module (beside `ms365_attachments.py`) holds the archive lookup (the single `business` drive from `list-drives`; `ittopia` → `admin` → year → month by id with `list-folder-files` from `root`, names matched case-insensitively; month names from a fixed English list) and the read wrapper `ms365_list_invoice_archive(year, month=None)`, added to `_TOOL_POLICY`'s wrappers. It returns names and sizes in a month's folder, or a year's month folders and their file names; a missing year or month answers that the Invoice archive holds nothing there; a missing `Documents/ittopia/admin` is an error. The description says it matches names only.
- The MS365 stand-in (`fixture_world.ms365`) gains `list-drives` and `list-folder-files` with the pinned server's argument shapes (`driveId`, `driveItemId`, OData options without `$`), over a drive directory named by `FIXTURE_WORLD_MS365_DRIVE`, seeded from `src/fixture_world/data/ms365/drive/` (an `Documents/ittopia/admin/2026/<Month>/` tree with a few Purchase invoice PDFs). Items get stable ids. The existing failure modes apply.

**Blocked by:** None (can start immediately)

**Status:** resolved

- [x] The stand-in's argument shapes match the pinned server's listing: check them against the real server's tool listing, not from memory
- [x] Through `load_all_tools(fixtures=True)`: `ms365_list_invoice_archive` is bound and classified read; `ms365_list-drives` and `ms365_list-folder-files` are not bound
- [x] Listing a seeded month returns its file names; a missing month says the Invoice archive holds nothing there; a missing `Documents/ittopia/admin` is an `Error:` line
- [x] The stand-in's logged-out mode gives a result naming the login command
- [x] A wrapper with no classification is still a Write action (a test pins the default)
- [x] The full suite passes (`uv run pytest -m "not live and not browser"`)

Spec: `../spec.md` (Loader; The Invoice archive tools; Fixture world and evals). ADR-020.

## Comments

- 2026-11-24: Built. `ToolWrapper.classification` (default `WRITE`; the loader binds a `READ` wrapper with `read_tool`). New `src/agent/tools/ms365_invoice_archive.py`: `InvoiceArchive` (the single `business` drive; `Documents/ittopia/admin`/year/month walked by id from `root`, case-insensitive; `MONTHS` fixed English list) and `ms365_list_invoice_archive(year, month=None)` (month is 1–12; it replaces `list-folder-files`; a transient failure is re-raised so the graph retries the read). `ENABLED_TOOLS` gains `DRIVE_TOOLS` (`list-drives`, `list-folder-files`). The stand-in serves both over `FIXTURE_WORLD_MS365_DRIVE` (default `<tmp>/fixture_world_ms365_drive`, copied from `data/ms365/drive/` when missing: 2026/October holds `kpn-factuur-123456.pdf` and `CH-2026-1044.pdf`, 2026/September holds `Factuur.pdf`, all made-up PDFs with a text layer); ids are derived from the path. The argument shapes were checked against the pinned 0.159.1 package's generated client and `graph-tools.js` in the npx cache (path params `driveId`/`driveItemId`; `select`/`orderby`/`expand` as a string or a list; `fetchAllPages`, `skiptoken`, `includeHeaders`, `excludeResponse` added). The listing has no `quickXorHash` yet (ticket 04). Tests: `tests/test_invoice_archive.py` (stand-in shapes, seeds, 404, failure switch; the wrapper bound as a read, month, year, case-insensitive names, missing month/year, missing admin, logged out), `tests/test_mcp_loader.py` (default and read wrapper classification, drive tools enabled and never exposed), the updated listing in `tests/test_fixture_world_ms365.py`. Full suite green.
