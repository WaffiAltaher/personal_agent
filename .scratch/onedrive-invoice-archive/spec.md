# Spec: Purchase invoices Uploaded to OneDrive, and Processed together with Informer

Status: ready-for-agent

Source: the grilling session of 2026-11-24 (Q1–Q12). Vocabulary follows `GLOSSARY.md` (Purchase invoice, Upload to Informer, Upload to OneDrive, Process, Processed, Invoice archive, Write action, Approval, Agent folder, Fixture world). The decision record is ADR-020, which extends ADR-015's wrapper pattern. Decisions also respect ADR-005 (the MS365 server owns the Microsoft login), ADR-010 (classification fails closed), ADR-011 (the Fixture world is the only test target), ADR-012 (Approval shows a Write action's raw arguments) and ADR-019 (Upload to Informer by e-mail).

## Problem Statement

The owner Processes a Purchase invoice once it is paid: they Upload it to Informer and Upload it to OneDrive, into the Invoice archive (`Documents/ittopia/admin/<year>/<Month in English>/` in their ITtopia OneDrive). The agent can Upload to Informer (ADR-019) but can't reach OneDrive at all, so the second half is done by hand, and "is this invoice Processed?" or "which October invoices are Processed?" means opening OneDrive and comparing files by eye.

The pinned MS365 server (`@softeria/ms-365-mcp-server@0.159.1`) has drive tools, but the agent doesn't enable them. They reach the whole OneDrive by drive and item id, `upload-file-content` overwrites without warning and takes the bytes as base64 in the call, and `create-upload-session` returns a pre-authenticated `uploadUrl` without ever sending the bytes.

## Solution

Three agent-side tools on the MS365 server, fixed to the Invoice archive, over the server's drive tools, which are enabled but never bound (as `ms365_save_attachment` wraps `download-bytes-to-file`, ADR-015):

- a read that lists a year's or a month's folder of the Invoice archive;
- a read, the Processed check, that says whether a local PDF's contents are already in the month folder of its invoice date, and where an Upload to OneDrive would put it;
- a Write action, Upload to OneDrive, that puts a local PDF in the month folder of its invoice date, creating a missing year or month folder, never overwriting, with the bytes sent by agent code through a Graph upload session.

A local read tool extracts a PDF's text so that the model can read the invoice date. A Process is the Upload to Informer and the Upload to OneDrive proposed together under one Approval and run concurrently. A new prompt version asks "Process instead?" before a single upload when the other one is missing, and ends every answer about a Purchase invoice with its status. The owner logs in to Microsoft once more, because the enabled drive tools add the `Files.ReadWrite` scope the Azure app already grants.

## User Stories

1. As the owner, I want to ask the agent to Process a paid Purchase invoice and approve once, so that both uploads happen without a second prompt.
2. As the owner, I want an Upload to OneDrive to put the file in `Documents/ittopia/admin/<year>/<Month>/` for its invoice date, so that the Invoice archive stays sorted the way the accountant and I look invoices up.
3. As the owner, I want the Approval to show the full target path, for example `Documents/ittopia/admin/2026/October/kpn-factuur-123456.pdf`, so that I know exactly where the file lands before I approve.
4. As the owner, I want a missing year or month folder created, so that the first invoice of a month needs no setup.
5. As the owner, I want the file name kept exactly as I received it, so that I can find it next to the e-mail it came with.
6. As the owner, I want nothing in OneDrive ever overwritten, so that an upload can't destroy an archived invoice.
7. As the owner, I want an upload of contents already in the month folder to do nothing and say it was already Uploaded to OneDrive, so that a repeated request doesn't create a copy.
8. As the owner, I want a different file with a taken name uploaded under OneDrive's own rename (for example `Factuur 1.pdf`), shown in the Approval, so that suppliers' generic names don't block an upload.
9. As the owner, I want to ask whether an invoice I have in Downloads is Processed and get an answer based on its contents, not its name, so that two different `Factuur.pdf` files aren't confused.
10. As the owner, I want to ask which invoices of a month are Processed and get the names in that month's folder, told that only names were matched, so that I know how far to trust the answer.
11. As the owner, I want the agent to read the invoice date from the PDF, and ask me when the PDF is a scan with no text, so that a guessed date never files an invoice in the wrong month.
12. As the owner, when I ask for only one upload and the other one hasn't happened, I want to be asked "Process instead?", so that I don't leave an invoice half Processed by accident.
13. As the owner, when the other upload has already happened, I want the agent to just do what I asked, so that I'm not asked a pointless question.
14. As the owner, I want every answer about a Purchase invoice to end with "Uploaded to Informer: yes (date)/no · Uploaded to OneDrive: yes (path)/no", so that I always see where it stands.
15. As the owner, I want a Process where one upload fails reported as such, with the remaining step offered on its own, so that I can finish it later.
16. As the owner, I want the agent's OneDrive reach limited to the Invoice archive, so that no instruction or bug can read or change the rest of my OneDrive.
17. As the owner, I want the file's bytes never to pass through the model, and no Microsoft token held by the agent, so that the upload keeps ADR-005's single login.
18. As the owner, I want evals to grade a Process on what the stand-in's Invoice archive and sent log actually hold, so that a run that files the wrong month or skips a step fails.

## Implementation Decisions

### Route and login

- The pinned Softeria server, the same Azure app and the same keychain login (ADR-005). Not Microsoft's Work IQ OneDrive MCP server (it needs Microsoft 365 Copilot and Agent 365 licences, admin enablement and its own hosted login, and limits files to 5 MB).
- `ENABLED_TOOLS` in `src/agent/tools/ms365_mcp.py` gains the drive tools the wrappers use: `list-drives`, `list-folder-files`, `create-onedrive-folder`, `create-upload-session` (and `get-drive-item` only if a wrapper needs it). None of them joins `EXPOSED_TOOLS` or `READ_TOOLS`. With them the server requests `Files.ReadWrite` (it collapses `Files.Read` into it). The Azure app already granted it delegated before the owner's current login, and a token carries every permission granted to the app (ADR-019), so no new login is expected; the probe (ticket 02) confirms it. If Graph refuses anyway, the server's login error names the login command, as today.
- `upload-file-content` is never enabled: it overwrites without warning and carries the bytes in the call.

### Loader

- `ToolWrapper` gains a classification (read or Write action), default Write action. Today the loader wraps every wrapper in `write_action(...)`; a read wrapper is bound with `read_tool(...)` instead. The listing and Processed-check wrappers are reads; the Upload to OneDrive is a Write action.
- Each wrapper names the drive tool it replaces, so that a server without it skips the wrapper with the existing warning, and a test pins that none of the drive tools is bound.

### The Invoice archive tools

All three are built on the MS365 server's tools by unprefixed name, as `ms365_save_attachment` is, and return strings: a result, or a line starting `Error:`.

- **Locating the archive.** The drive is the single `business` drive from `list-drives` (none or more than one is an error). Folders are found level by level by id with `list-folder-files`, starting at `root`: `Documents`, `ittopia`, `admin`, the year, the month. Names match case-insensitively, as OneDrive does. A missing `Documents/ittopia/admin` is an error and is never created.
- **Month folder.** The year and month of the invoice date printed on the invoice, the month written out in English from a fixed list, never the system locale: `2026/October`.
- **`ms365_list_invoice_archive(year, month=None)`** (read): the names (and sizes) in that month's folder, or with no month, the month folders of that year and their file names. A missing year or month folder answers that the Invoice archive holds nothing there, not an error. The description says that it matches names only.
- **`ms365_check_invoice_archive(path, invoice_date)`** (read, the Processed check): reads the local PDF, computes its `quickXorHash`, lists the month folder and compares with each file's `file.hashes.quickXorHash`, never downloading. It answers one of:
  - Processed: these contents are in the month folder as `<archive path>`;
  - not Processed, with the target path an Upload to OneDrive would use: `Documents/ittopia/admin/<year>/<Month>/<file name>`, or, when a different file already has that name, the name OneDrive's rename will give it (OneDrive's pattern, `<stem> 1<ext>`, `<stem> 2<ext>`, …, seen in the probe; an unfinished upload session also holds its name until it expires, so the result's real name wins over the predicted one) and a line saying so.
- **`ms365_upload_to_onedrive(path, invoice_date, target_path)`** (Write action, the Upload to OneDrive):
  - Reads the same local file rules as the Processed check (below).
  - Recomputes the target path from the invoice date and the file name, and refuses unless `target_path` equals it, or equals the renamed path when the name is taken by different contents. A refusal says the folder changed and to run the Processed check again. This puts the full path into the Approval's raw arguments without a display hook in the graph (ADR-015's `file_name`).
  - Same contents already in the month folder, under any name: nothing is uploaded. The first line starts `NOT UPLOADED:` and says it was already Uploaded to OneDrive as `<archive path>`; the description tells the model to repeat it.
  - Creates a missing year, then month, folder with `create-onedrive-folder` (`conflictBehavior: fail`); a conflict from a folder created meanwhile is answered by listing again.
  - Creates the upload session with `create-upload-session` on the month folder for the new file (`driveItemId` `{monthFolderId}:/{file name}:`, body `item` with only `"@microsoft.graph.conflictBehavior": "rename"`: adding `name` makes Graph answer 400 `invalidRequest`), then PUTs the bytes to the returned `uploadUrl` in one range (`Content-Length`, `Content-Range: bytes 0-<n-1>/<n>`), with **no** `Authorization` header, using `httpx`. A failed PUT is followed by a best-effort `DELETE` of the session.
  - Success returns the archive path OneDrive reports in the created driveItem (which may carry the rename suffix) and the size.
  - The `uploadUrl` is a bearer capability: it never appears in a tool result, an error text, a log line or a trace. A server tool the wrapper calls inherits the run's callbacks (Langfuse) and is traced with its output, so `create-upload-session` is called with no callbacks.
  - Never retried (it's a Write action); a login error names the login command, as the save wrapper's does.
- **Local file rules** (both tools taking `path`): the file must be a `.pdf` with the `%PDF-` magic, inside the Downloads folder the Informer server checks (`INFORMER_DOWNLOADS_DIR`, default `~/Downloads`, which contains the Agent folder; the agent reads it through a new `Settings` field, so a value in `.env`, which the Informer server reads itself, counts for both), and at most 25 MB (one PUT range; Graph's per-request limit is 60 MiB). So every file that can be Uploaded to Informer can be Uploaded to OneDrive.
- **`quickXorHash`** is computed in agent code (no dependency) from Microsoft's published algorithm (160-bit block, shift 11, length XORed into the last 8 bytes, base64), and tested against values the probe records from the real OneDrive.

### Reading the invoice date

- A new local read tool, `read_pdf_text(path)`, wrapped in `read_tool(...)`, returns the text of a local PDF's first pages, capped like `read_file`. It uses a new dependency (`pypdf`, pure Python). A PDF with no extractable text answers that it has no text layer (probably a scan) and that the agent must ask the owner for the invoice date.
- Its eval stand-in confines paths to the run's Downloads folder (the files root), as `fixture_read_file` does, and is bound in its place through the harness's `EVAL_FILE_STAND_INS`.
- The model passes the date it read as `invoice_date` (`YYYY-MM-DD`); the tools compute the folder from it.

### Process

- No new tool and no graph change: the model proposes `informer_upload_purchase_invoice` and `ms365_upload_to_onedrive` in one turn, `human_review_node` shows both in one Approval, and `ToolNode` runs them concurrently. No order is enforced.
- If one fails, the agent reports which and offers the remaining step on its own.

### Prompt

- A new prompt version, `v7`, written out in full, `v6` plus the rules below, and made the default. Released versions never change; `RELEASED` gains its sha256.
  - Before Uploading a Purchase invoice, read the invoice date with `read_pdf_text`, and ask the owner when there is none.
  - Before an Upload to OneDrive, run the Processed check and pass its target path unchanged.
  - When the owner asks for only one upload and the other is missing (Informer: `informer_check_purchase_invoice` reports no earlier upload; OneDrive: the Processed check says not Processed), ask "Process instead?" first. When the other is already done, just do what was asked.
  - To Process, propose both uploads together, in one turn.
  - Every answer about a Purchase invoice ends with one line: `Uploaded to Informer: yes (<date>)/no · Uploaded to OneDrive: yes (<path>)/no`. The Informer status comes from `informer_check_purchase_invoice`'s record of earlier uploads of the same contents; the OneDrive status from the Processed check, or, without a file, the listing, said to match names only.

### Fixture world and evals

- The MS365 stand-in gains the drive tools the wrappers use, with the pinned server's argument shapes (`driveId`, `driveItemId`, OData options without `$`, `body`), and a fake Invoice archive:
  - a drive directory named by a new `FIXTURE_WORLD_MS365_DRIVE` variable (default under the temp directory), seeded from `src/fixture_world/data/ms365/drive/`, with stable item ids and a `quickXorHash` per file;
  - `create-upload-session` records a pending session and returns an `uploadUrl` that is not a real URL; the agent's PUT is a seam, and `ms365_fixture_server()` supplies one that completes the stand-in's session (applying `conflictBehavior: rename` under the file lock), so no test opens a socket;
  - its existing failure modes apply to the drive tools, plus a switch that fails only the drive tools (`FIXTURE_WORLD_MS365_DRIVE_FAILURE=transient`), and a helper reads the archive back.
- The harness gives each run its own seeded drive directory. `ExpectedOutcome` gains `archived_files` (archive paths, each with the expected bytes), graded like `saved_files`.
- New eval scenarios: Process approved (one sent message and one archived file, one Approval), Upload to OneDrive alone with Informer not done (asks "Process instead?", uploads nothing), Upload to OneDrive alone with Informer done (seeded Informer upload log; no question, one archived file), Processed check by file, Processed list by month (names only, said so), name clash with the same contents (no-op), name clash with different contents (renamed), a scanned PDF (asks for the date, uploads nothing), and a Process with the drive failing (Informer upload done, the OneDrive failure reported and the remaining step offered).

## Testing Decisions

- No test reaches Microsoft (ADR-011): the drive wrappers run only against the stand-in, through `load_all_tools(fixtures=True)`, as `tests/test_save_outlook_attachment.py` does. No live model calls (the owner's quota rule); graph and eval tests use the scripted model.
- The real PUT is tested with `httpx.MockTransport`: one request, the full bytes, `Content-Range`, no `Authorization` header, and the `uploadUrl` absent from the result, also on failure.
- `quickXorHash` against the values the probe records (ticket 02), plus the empty input.
- Policy pins: the drive tools are in `ENABLED_TOOLS`, none is bound, `upload-file-content` is not enabled, the two archive reads are classified read and the upload a Write action.
- Wrapper behaviour through the stand-in: folder lookup from `root`, a missing `Documents/ittopia/admin`, created year and month folders, the target-path check, the same-contents no-op, the rename, the login error naming the command, the Processed check by contents (a same-named different file is not Processed), and two concurrent uploads to a new month folder.
- `read_pdf_text` on a seeded text PDF and on a PDF with no text layer.
- Prompt tests as for earlier versions: `v7` starts with `v6`, is a full literal, is the default, and is in `RELEASED`.
- The eval scenarios above, run with the scripted model in tests, as the upload scenarios are.

## Out of Scope

- Sales invoices, and any OneDrive folder other than the Invoice archive.
- Renaming or moving files in OneDrive, and deleting anything.
- Payment: the agent doesn't check or record whether an invoice is paid; Processing it is the owner's statement that it is.
- Files over 25 MB, and multi-range uploads.
- Reading invoice dates from scans (OCR).
- Getting the PDF from e-mail: that stays `ms365_save_attachment`/`save_gmail_attachment`, then a Process.

## Further Notes

- Graph references: upload sessions (`driveitem-createuploadsession`: no `Authorization` header on the PUT; 409 `nameAlreadyExists`), folder creation (`driveitem-post-children`: one level per request), hashes (`quickXorHash` is the only hash guaranteed on OneDrive for Business), addressing (`root:/path:` and `{itemId}:/{name}:`).
- The pinned server percent-encodes path parameters, so `{parentId}:/{name}:` reaches Graph as `{parentId}%3A%2F{name}%3A`. The probe (ticket 02) found Graph accepts it for `create-upload-session`.
- The pinned server has no `/me/drive` tool, hence `list-drives`.
- When bumping the MS365 pin, review the drive tools' argument shapes, `create-upload-session`'s contract (the server doesn't PUT), and the path-parameter encoding.
