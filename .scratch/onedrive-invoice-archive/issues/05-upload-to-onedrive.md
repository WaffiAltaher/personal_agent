# 05: Upload to OneDrive through an upload session, never overwriting

**Type:** task

**What to build:** `ms365_upload_to_onedrive(path, invoice_date, target_path)`, a Write action wrapper replacing `create-upload-session`.
- `ENABLED_TOOLS` gains `create-onedrive-folder` and `create-upload-session` (not `upload-file-content`).
- Same local file rules as the Processed check. Recomputes the target path and refuses unless `target_path` equals it, or the renamed path when the name is taken by different contents; the refusal says to run the Processed check again.
- Same contents already in the month folder under any name: nothing uploaded, first line `NOT UPLOADED:` saying it was already Uploaded to OneDrive as `<archive path>`; the description tells the model to repeat it.
- Creates a missing year, then month, folder (`conflictBehavior: fail`; a conflict means list again). A missing `Documents/ittopia/admin` is an error.
- Creates the session on the month folder for the new file (the form ticket 02 found to work: `driveItemId` `{monthFolderId}:/{file name}:`, body `item` with only `"@microsoft.graph.conflictBehavior": "rename"`, never `name`, which Graph refuses with 400), then PUTs the bytes through a seam: the real PUT uses `httpx`, one range, `Content-Length` and `Content-Range`, no `Authorization` header, and a best-effort `DELETE` of the session on failure. `ms365_fixture_server()` supplies a PUT that completes the stand-in's session.
- Returns the archive path from the created driveItem (with any rename suffix) and the size. The `uploadUrl` never appears in a result, an error, a log line or a trace; `create-upload-session` is called without the run's callbacks, which would otherwise trace its output.
- The stand-in gains `create-onedrive-folder` and `create-upload-session` (pinned shapes), sessions recorded under the drive directory, completion applying `rename` under the file lock, a helper to read the archive back, and `FIXTURE_WORLD_MS365_DRIVE_FAILURE=transient`, which fails only the drive tools (Graph 503).

**Blocked by:** 02, 04

**Status:** resolved

- [x] Through `load_all_tools(fixtures=True)`: an upload to a new month creates the year and month folders and one file with the exact bytes and name; the result names `Documents/ittopia/admin/<year>/<Month>/<name>`
- [x] A different file under a taken name lands under OneDrive's rename; the existing file is unchanged
- [x] The same contents again: `NOT UPLOADED:`, nothing written
- [x] A `target_path` that doesn't match is refused before anything is created
- [x] Two concurrent uploads of different files to a new month folder both land, in one month folder
- [x] The real PUT, against `httpx.MockTransport`: one request with the full bytes and `Content-Range`, no `Authorization` header; on a failed PUT the session is deleted and the `uploadUrl` is absent from the error
- [x] With a callback handler on the run, no callback receives the `uploadUrl` (a nested server tool call inherits the run's callbacks)
- [x] Logged-out and the drive failure switch are reported as the upload's error, nothing written, never retried; the logged-out one names the login command
- [x] Policy pins: no drive tool is bound, `upload-file-content` is not enabled, the upload is a Write action
- [x] The full suite passes (`uv run pytest -m "not live and not browser"`)

Spec: `../spec.md` (The Invoice archive tools; Fixture world and evals). ADR-020.

## Comments

- 2026-11-24: Built. `ms365_upload_to_onedrive` in `src/agent/tools/ms365_invoice_archive.py`: `upload_to_onedrive(put) -> ToolWrapper` (Write action, replaces `create-upload-session`); the real server gets `httpx_put`, `ms365_fixture_server()` gets `fixture_world.ms365.put_upload_session`. Order: local file rules, the Processed check (`check_archive` now takes an optional `InvoiceArchive`, to reuse the drive id), `NOT UPLOADED:` for the same contents (before the target check, so a repeat with the old target path is a no-op, not a refusal), the target-path check, year/month creation (`fail`; `nameAlreadyExists` lists again), the session (`{monthId}:/{name}:`, `item` with only `rename`, called with `{"callbacks": []}`), the PUT. The result names the returned driveItem's name. Every failure, transient included, is an `Error:` string. `httpx_put` also keeps the URL out of httpx's INFO request line with a logger filter. `ENABLED_TOOLS` gains `create-onedrive-folder` and `create-upload-session`. The stand-in gains both tools (pinned shapes, `confirm` included), sessions in `<drive>/.upload-sessions/`, `put_upload_session` (rename under `_exclusive(drive root)`), `archived_files(path=None)` and `FIXTURE_WORLD_MS365_DRIVE_FAILURE=transient`. The stand-in's unfinished sessions don't hold names. Tests: `tests/test_upload_to_onedrive.py`, and pins in `tests/test_fixture_world_ms365.py` and `tests/test_mcp_loader.py`. Full suite green.
