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

**Status:** ready-for-agent

- [ ] Through `load_all_tools(fixtures=True)`: an upload to a new month creates the year and month folders and one file with the exact bytes and name; the result names `Documents/ittopia/admin/<year>/<Month>/<name>`
- [ ] A different file under a taken name lands under OneDrive's rename; the existing file is unchanged
- [ ] The same contents again: `NOT UPLOADED:`, nothing written
- [ ] A `target_path` that doesn't match is refused before anything is created
- [ ] Two concurrent uploads of different files to a new month folder both land, in one month folder
- [ ] The real PUT, against `httpx.MockTransport`: one request with the full bytes and `Content-Range`, no `Authorization` header; on a failed PUT the session is deleted and the `uploadUrl` is absent from the error
- [ ] With a callback handler on the run, no callback receives the `uploadUrl` (a nested server tool call inherits the run's callbacks)
- [ ] Logged-out and the drive failure switch are reported as the upload's error, nothing written, never retried; the logged-out one names the login command
- [ ] Policy pins: no drive tool is bound, `upload-file-content` is not enabled, the upload is a Write action
- [ ] The full suite passes (`uv run pytest -m "not live and not browser"`)

Spec: `../spec.md` (The Invoice archive tools; Fixture world and evals). ADR-020.

## Comments
