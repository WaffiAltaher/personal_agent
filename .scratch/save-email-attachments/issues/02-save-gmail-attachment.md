# 02: Save a Gmail attachment into the agent folder's gmail/ subfolder

**What to build:** The first complete path through the feature. Reading a Gmail message now lists its attachments, and the owner can ask the agent to save one. The save stops for Approval, and on approval the file appears in `<agent folder>/gmail/` under the attachment's own name. The full path comes back to the agent. The shared save rules built here are reused unchanged by the Outlook ticket.

Demo: `python -m agent.cli --fixtures "save the PDF from <seeded personal email>"`, approve, and the file is in the agent folder's `gmail/` subfolder.

**Blocked by:** None (can start immediately)

**Status:** resolved

Agent folder:
- [x] A new setting, the agent folder, defaults to `~/Downloads/personal_agent`. Tests set it to a temporary directory.
- [x] The save creates the agent folder and its `gmail/` subfolder when they're missing

Shared save rules (one module, written to be reused by the Outlook save):
- [x] The file is named with the attachment's own file name, reduced to a bare name: directory parts and path separators are stripped, and an empty or dot-only name falls back to `attachment`
- [x] The final path always resolves inside the mailbox's subfolder; anything else is refused
- [x] If a file with identical bytes already exists in the same name family (`invoice.pdf`, `invoice (1).pdf`, …), nothing is written and the result says "already saved as <path>"
- [x] Otherwise the first free name in the family is used: `invoice.pdf`, then `invoice (1).pdf`, then `invoice (2).pdf`
- [x] An existing file is never overwritten
- [x] Files over 25 MB are refused: checked against the listed size before downloading, and against the actual bytes always
- [x] Any file type is accepted
- [x] The result is a plain string: success names the full path and the size; every refusal or failure starts with `Error:` and nothing raises

Gmail:
- [x] `get_gmail_message` additionally lists the message's attachments (file name, size, attachment ID). The listed ID is the MIME part ID, since Gmail's attachment ID changes on every fetch. A part is inline when its `Content-Disposition` is `inline`, or when it has none and has a `Content-ID`; `Content-Disposition: attachment` is never inline. Inline parts are hidden unless an optional `include_inline` argument is true.
- [x] `save_gmail_attachment(message_id, attachment_id, file_name, include_inline=False)` fetches the bytes through the Gmail API's attachments endpoint and applies the save rules into `gmail/`
- [x] The save is refused when `file_name` doesn't exactly equal the attachment's real file name, when the attachment is inline and `include_inline` is false, or when it's an attached email (`message/rfc822`)
- [x] `save_gmail_attachment` is wrapped in `write_action(...)` and is never `read_tool(...)`
- [x] No OAuth scope change: the existing `gmail.modify` scope covers this

Fixture world:
- [x] One seeded personal Gmail message has a PDF attachment and an inline logo
- [x] The Gmail stand-in's `has:attachment` search becomes data-driven instead of always false
- [x] `get_gmail_message` and `save_gmail_attachment` have Fixture world stand-ins with the same names and arguments, registered like the other Google stand-ins

Tests (tool seam: the tools as `load_all_tools(fixtures=True)` returns them, invoked directly, with the agent folder in a temporary directory):
- [x] An approved-path save writes the seeded bytes into `gmail/`
- [x] A name that tries to escape the subfolder (e.g. `../x.pdf`) still lands inside it
- [x] Different contents with the same name get `(1)`, then `(2)`
- [x] An identical repeat writes nothing and returns the existing path
- [x] Nothing is ever overwritten
- [x] A `file_name` mismatch is refused
- [x] The 25 MB cap refuses an oversized attachment
- [x] An inline attachment is refused without `include_inline` and saved with it
- [x] Folders are created on the first save
- [x] `get_gmail_message` lists the PDF and hides the logo by default
- [x] Approval seam: the save pauses for Approval, and a reject writes nothing (prior art: the Write action classification tests and the MS365 Draft reject test)
- [x] The whole suite passes, including the existing check that every bound tool is read-classified or gated by Approval

Traps:
- Gmail returns attachment data base64url-encoded, not standard base64.
- Don't add mailbox-specific logic to the Approval step or the graph. `file_name` is an argument precisely so the generic Approval prompt shows it.
- The real Gmail tool can't be called in tests (ADR-011). Test through the stand-in, and keep the real tool's decoding and part-walking in functions the stand-in shares.

Spec: `../spec.md` (The agent folder, The save rules, Tool contract, Gmail, Fixture world).
