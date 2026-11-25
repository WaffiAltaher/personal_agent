# 02: Probe the pinned server's drive tools and the upload session against the real OneDrive

**Type:** research

**What to build:** One probe, run with the owner's go-ahead in the session, of the facts ADR-020 relies on that no document settles. It runs the pinned `@softeria/ms-365-mcp-server@0.159.1` directly (not through the agent), with only the drive tools enabled, in a throwaway folder `agent-probe-2026-11-24` at the OneDrive root (never in `Documents/ittopia/admin`), which the owner deletes afterwards. Uploaded files are small made-up PDFs and text files, never real invoices. Answers go under `## Answer`.

To find out, by running it:
- Does the owner's existing login reach OneDrive without logging in again (`Files.ReadWrite` was granted to the app before that login)? If Graph answers 401/403, record the error verbatim and stop: a re-login becomes a manual ticket.
- `list-drives`: does it return exactly one drive with `driveType` `business`? Record the shape (not the id).
- `list-folder-files` with `driveItemId` `root`, and on a subfolder: does each file carry `file.hashes.quickXorHash` in the listing, without `$select` or `$expand`? Does `$select` keep it?
- `create-onedrive-folder` with `"@microsoft.graph.conflictBehavior": "fail"` on an existing name: the exact error text the server returns (status 409, code).
- `create-upload-session` with `driveItemId` `{folderId}:/{file name}:` (the server sends it percent-encoded as `{folderId}%3A%2F{file name}%3A`), body `item` with `name` and `"@microsoft.graph.conflictBehavior": "rename"`: does Graph accept it? Repeat with a name containing a space and a `#`. If it is refused, which form works through the server, if any.
- The PUT to the returned `uploadUrl`, one range, `Content-Range: bytes 0-<n-1>/<n>`, no `Authorization` header: status and the driveItem returned (name, size, `file.hashes`).
- A second upload of different contents under the same name with `rename`: the name OneDrive gives it (is it `<stem> 1<ext>`?), and a third (`<stem> 2<ext>`?).
- `quickXorHash` test vectors: the hash OneDrive reports for three files whose bytes are recorded in the answer (an empty file, a short text file, a small PDF), base64 as reported.
- How long one server start plus one tool call takes, to estimate an upload's cost (several starts).

**Blocked by:** None (can start immediately)

**Status:** resolved

- [x] Every question above is answered with what the server returned (error texts verbatim, ids and URLs redacted; the `uploadUrl` is never recorded)
- [x] The three hash vectors are recorded with their bytes (hex or base64), ready for ticket 04's test
- [x] Go or no-go for the encoded `{folderId}:/{name}:` form; if no-go, ADR-020's consequence is amended and ticket 05 is revised before it starts
- [ ] The probe folder is deleted by the owner, and that is recorded

Spec: `../spec.md` (The Invoice archive tools; Further Notes). ADR-020.

## Answer

Run 2026-11-24 from a scratch script over a stdio session to `@softeria/ms-365-mcp-server@0.159.1`, enabled tools `list-drives|list-folder-files|get-drive-item|create-onedrive-folder|create-upload-session`, the agent's client and tenant IDs, the owner's existing keychain login.

- **Login:** `verify-login` succeeded and every call below worked with the existing login: no new login needed for `Files.ReadWrite`.
- **`list-drives`:** exactly one drive, `driveType` `business`, name `Documenten`; keys `createdBy, createdDateTime, description, driveType, id, lastModifiedBy, lastModifiedDateTime, name, owner, quota, webUrl`.
- **Hashes in listings:** `list-folder-files` returns `file.hashes.quickXorHash` for every file without `$select`/`$expand` (only `quickXorHash`, no sha1/sha256), and `select: "name,size,file"` keeps it. Folders have no `file`.
- **Folder name clash:** `create-onedrive-folder` with `conflictBehavior` `fail` on an existing name: tool error `Microsoft Graph API error: 409 Conflict - {"error":{"code":"nameAlreadyExists","message":"Name already exists",…}}`. Nested creation by parent id works one level per call.
- **Encoded `{folderId}:/{name}:`:** **go.** Graph accepts it for `create-upload-session`, and so does `root:/<path>/<name>:`. But a body `item` containing `name` makes Graph answer `400 Bad Request` `invalidRequest` (`The request is malformed or incorrect.`); `item` with only `"@microsoft.graph.conflictBehavior": "rename"` works. `body` is required by the tool's schema.
- **PUT:** one range, `Content-Length` and `Content-Range: bytes 0-<n-1>/<n>`, no `Authorization`: `201` with the driveItem (`name`, `size`, `file.hashes.quickXorHash`). A 0-byte PUT to a session answers `400` (irrelevant: a PDF is never empty).
- **Rename:** different contents under an existing `Factuur.pdf` became `Factuur 1.pdf`, then `Factuur 2.pdf`. A name with a space and `#` (`kpn factuur #123.pdf`) arrived unchanged. **Surprise:** two upload sessions created for `probe.txt` and never PUT still held their names, so a later upload of `probe.txt` became `probe 2.txt` while the folder showed no `probe.txt` at all. A predicted rename can be wrong; trust the PUT's returned name.
- **`quickXorHash` vectors** (OneDrive's value; an implementation of 160-bit block, shift 11, length XORed into bytes 12–19, base64 matched all of them):
  - `hello onedrive probe\n` (21 bytes) → `aCZxY1vozLC8wQ1lNYMc0mCHMoA=`
  - `P` = `%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj 2 0 obj<</Type/Pages/Kids[]/Count 0>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n` (125 bytes) → `PQgwGNxkRuC1nY4pjMn9uFkXH8w=`
  - `P` + `%second\n` (133 bytes) → `9agwGNxkRuC1nY6pZgVctDpvnNc=`
  - `P` + `%third\n` (132 bytes) → `KQgwGNxkRuC1nY6pZxn8tTCHHNU=`
  - `P` + `%space-hash\n` (137 bytes) → `Z4i2KBBlS+q1nY6pagX8tjgPXNU=`
  - empty input → `AAAAAAAAAAAAAAAAAAAAAAAAAAA=` (computed locally only)
- **Cost:** server start about 1.2–2.1 s; calls 0.1–0.7 s each.
- **Probe folder:** `agent-probe-2026-11-24` at the OneDrive root, holding a `2026` subfolder and five small made-up files. Deletion by the owner: pending.

## Comments
