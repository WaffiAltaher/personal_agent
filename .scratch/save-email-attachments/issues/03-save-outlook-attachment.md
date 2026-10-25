# 03: Save an Outlook attachment into outlook/ through the confined wrapper

**What to build:** The owner can ask the agent to save an attachment from the ITtopia Outlook mailbox. The save stops for Approval, showing the attachment's real file name. On approval the file appears in `<agent folder>/outlook/`, under the same save rules as Gmail. Underneath, the pinned third-party server's `download-bytes-to-file` does the download, so the Outlook login stays inside the server (ADR-005). The model never sees that raw tool, or any path argument.

Demo: `python -m agent.cli --fixtures "save the attachment from <seeded Outlook message>"`, approve, and the file is in the agent folder's `outlook/` subfolder.

**Blocked by:** 02 (the shared save rules and the agent folder setting)

**Status:** resolved

- [x] A model-facing tool `ms365_save_attachment(message_id, attachment_id, file_name, include_inline=False)` exists and is classified as a Write action
- [x] It looks the attachment up with the server's `list-mail-attachments`. It refuses when `file_name` doesn't exactly equal the real name, when the attachment is inline (`isInline`) and `include_inline` is false, when it isn't a file attachment (attached emails and cloud links are refused with a reason), or when the listed size is over 25 MB.
- [x] It calls `download-bytes-to-file` with the attachment's `$value` path and a unique temporary name inside `outlook/`, then applies the shared duplicate and clash rules: it deletes the temporary file on an identical match, otherwise renames it to the chosen name. It never overwrites.
- [x] The result string matches the Gmail save's: the full path and size, or `Error: …`
- [x] `download-bytes-to-file` is enabled on the server, real and fixture alike, but is **never bound to the model**. The loader exposes `ms365_save_attachment` in its place, by name.
- [x] `download-bytes-to-file` stays excluded from the MS365 read allowlist
- [x] The server's enabled tools still exclude every send or other write, and no new Graph scope is requested
- [x] `list-mail-attachments` stays a read and is not wrapped

Fixture world:
- [x] The seeded Outlook message that already has `hasAttachments: true` gets a real PDF attachment and an inline logo, served by `list-mail-attachments`
- [x] The fake server's `download-bytes-to-file` stops being a stub that always errors. It writes the seeded bytes, refuses a relative path and refuses an existing file, like the real server.

Tests (the same tool seam as ticket 02):
- [x] The same rule tests as ticket 02, run against `outlook/`: confinement, `(1)`/`(2)`, identical repeat, never overwrite, `file_name` mismatch, size cap, inline refused or allowed, folders created
- [x] A Gmail save never writes into `outlook/`, and an Outlook save never into `gmail/`
- [x] `download-bytes-to-file` isn't among the bound tools, and `ms365_save_attachment` is
- [x] The fake `download-bytes-to-file` refuses a relative path and an existing file (prior art: the Fixture world MS365 tests)
- [x] Approval seam: the save pauses for Approval, and a reject writes nothing
- [x] The whole suite passes

Traps:
- The server annotates `download-bytes-to-file` as `readOnlyHint`. Classification must go by the allowlist, never by that annotation (ADR-010).
- The model-binding layer drops `additionalProperties` from tool schemas for Gemini. Check that the wrapper's schema binds cleanly.
- The temporary file must be removed on every failure path, so a failed save leaves no stray file in `outlook/`.

Spec: `../spec.md` (Outlook, Classification and Approval, Fixture world). ADR-015.
