# Spec: Save email attachments to the agent folder

Status: ready-for-agent

Source: the grilling session of 2026-10-25 (Q1–Q11). Vocabulary follows `GLOSSARY.md` (Write action, Approval, Purchase invoice, Draft, Fixture world). Decisions respect `docs/ARCHITECTURE_DECISIONS.md`, especially ADR-005 (consume the third-party MS365 server), ADR-010 (classification fails closed), ADR-011 (the Fixture world is the only test and eval target) and ADR-012 (Purchase invoice upload takes a local path).

## Problem Statement

Attachments reach the owner by email: Purchase invoices from suppliers in the ITtopia Outlook mailbox, and documents in their personal Gmail. The agent can read those emails but cannot keep the files. To hand a Purchase invoice to Informer, the owner has to open the email, download the attachment by hand and then tell the agent where it is. ADR-012 anticipated this gap: the upload takes a local path precisely so that "an email attachment" could later become a source, but nothing produces that file.

- In Outlook, the agent can list a message's attachments but has no tool that saves one. The third-party server's own save tool is deliberately kept from the model, because it writes to any absolute path while declaring itself read-only.
- In Gmail, reading a message returns only its text. Attachments are not mentioned at all, so the agent doesn't even know they exist.
- The agent has no folder of its own. The system prompt points it at a personal data folder that has nothing to do with saved mail.

## Solution

The agent can save an attachment from either mailbox into its own folder, `~/Downloads/personal_agent`, with one subfolder per mailbox: `gmail/` and `outlook/`. Each save is a Write action: the owner sees the mailbox, the message and the attachment's real file name in the Approval prompt, and nothing is written without approval. The agent never chooses a path. It names the attachment, and the tool decides where the file goes, keeps it inside that mailbox's folder, never overwrites anything, and doesn't save the same file twice. The saved file's full path comes back to the agent, so "save the invoice from that email and upload it to Informer" works in one conversation.

Reading a Gmail message now lists its attachments. Signature logos, tracking pixels and other inline images are hidden by default in both mailboxes.

The system prompt names `~/Downloads/personal_agent` as the agent's folder. While doing this, every prompt version is rewritten to hold its full text instead of being built from an earlier version, so a future change is a copy-and-edit.

## User Stories

1. As the owner, I want to ask the agent to save an attachment from an Outlook email, so that a supplier's Purchase invoice is on my computer without opening Outlook.
2. As the owner, I want to ask the agent to save an attachment from a Gmail email, so that my personal documents are kept the same way.
3. As the owner, I want "save the invoice from that email and upload it to Informer" to work in one conversation, so that a Purchase invoice goes from inbox to accountant without my touching the file.
4. As the owner, I want every save to stop for my Approval, so that nothing is written to my computer without my knowing.
5. As the owner, I want the Approval prompt to show the attachment's real file name, so that I can see what I'm approving and not just opaque IDs.
6. As the owner, I want a save to be refused when the file name the agent shows doesn't match the real attachment, so that a harmless-looking name can't hide a different file.
7. As the owner, I want rejected saves to write nothing, so that "reject" really means nothing happened.
8. As the owner, I want Outlook attachments to land only in `~/Downloads/personal_agent/outlook/` and Gmail attachments only in `~/Downloads/personal_agent/gmail/`, so that I always know where saved mail is and which mailbox it came from.
9. As the owner, I want the agent to be unable to write anywhere else on my computer through these tools, so that a confused or manipulated model can't overwrite my files.
10. As the owner, I want the folders created automatically on the first save, so that I don't have to set anything up.
11. As the owner, I want a file saved under the attachment's own name, so that it's recognisable in Finder.
12. As the owner, I want a second, different file with the same name saved as `invoice (1).pdf`, `invoice (2).pdf`, so that the monthly `invoice.pdf` from a supplier never fails and never replaces last month's.
13. As the owner, I want saving the same attachment again to write nothing and tell me where it already is, so that a repeated request doesn't clutter my folder.
14. As the owner, I want existing files never overwritten, so that saving can't destroy anything.
15. As the owner, I want attachments larger than 25 MB refused with a clear reason, so that a huge file can't fill my disk.
16. As the owner, I want any file type accepted, so that legitimate attachments like `.zip` exports aren't blocked; the Approval prompt is where I catch something suspicious.
17. As the owner, I want inline images (logos, tracking pixels, pasted screenshots) left out of attachment lists by default, so that "save the attachments" saves the real files and the Approval prompt isn't full of logos.
18. As the owner, I want to still be able to save inline images when I explicitly ask for "the images in the email", so that a pasted screenshot isn't unreachable.
19. As the owner, I want reading a Gmail message to tell me which attachments it has (name, size), so that I can decide what to save.
20. As the owner, I want the agent to tell me the full path of every saved file, so that I can open it or use it in a follow-up request.
21. As the owner, I want a failed save (expired login, deleted message, mailbox outage) reported as an error rather than crashing the run, so that the rest of my request still gets answered.
22. As the owner, I want a failed save never retried automatically, so that a Write action happens at most once per Approval.
23. As the owner, I want the system prompt to name `~/Downloads/personal_agent` as the agent's folder, so that it looks there first for files it saved.
24. As the owner, I want the agent's reading tools and the Informer upload to keep working on files elsewhere in Downloads, so that "upload the PDF I just downloaded" still works.
25. As the owner, I want a saved attachment to be acceptable to the Informer upload without moving it, so that the inbox-to-accountant flow needs no manual step.
26. As the owner, I want the existing Gmail login to keep working, so that adding attachments doesn't make me log in again.
27. As the maintainer, I want every prompt version to hold its full text, so that a new version is a copy-and-edit and the text of any version is readable in one place.
28. As the maintainer, I want flattening V3 and V4 to leave their text byte-for-byte unchanged, so that traces and eval results tagged `v3`/`v4` stay truthful.
29. As the maintainer, I want the new prompt to be a new version (`v5`) and the default, so that eval comparisons can tell the prompt change apart from a model change.
30. As the maintainer, I want the save rules tested against the Fixture world for both mailboxes, so that tests never touch real mail or my real Downloads folder.
31. As the maintainer, I want the agent folder to be a setting, so that tests and evals can point it at a temporary directory.
32. As the maintainer, I want the third-party server's raw save tool never bound to the model, so that its "write anywhere" behaviour stays unreachable even though our Outlook save uses it underneath.
33. As the maintainer, I want eval scenarios for an approved Gmail save, a rejected Outlook save and the Outlook-to-Informer chain, so that the feature's real purpose is measured, not just its parts.

## Implementation Decisions

### The agent folder

- A new setting, the **agent folder**, defaults to `~/Downloads/personal_agent`. Tests and evals point it at a temporary directory. Each mailbox has a fixed subfolder: `gmail/` and `outlook/`. A save tool creates its subfolder (and the agent folder) when missing.
- The agent folder is where the agent starts, not a limit. `read_file`, `list_directory` and the Informer upload keep their current reach. The Informer upload already accepts any path under `~/Downloads`, subfolders included, so saved attachments are uploadable as they are.

### The save rules (shared by both mailboxes)

One shared module owns the rules, so both mailboxes behave identically:

- **Name:** the attachment's own file name in a typeable form (Unicode NFKC, every whitespace run one plain space, so a non-breaking space becomes a space), reduced to a bare name. The `file_name` check compares the same typeable forms (any directory parts or path separators stripped; an empty or dot-only name gets a neutral fallback such as `attachment`). The model never supplies a path.
- **Confinement:** the final path must resolve inside that mailbox's subfolder; anything else is refused.
- **Duplicates:** before writing, compare the bytes with every existing file in the subfolder of the same name family (`invoice.pdf`, `invoice (1).pdf`, `invoice (2).pdf`, …). On a match, write nothing and return "already saved as <path>".
- **Clash:** otherwise use the first free name in the family: `invoice.pdf`, then `invoice (1).pdf`, `invoice (2).pdf`.
- **Never overwrite:** a write never replaces an existing file.
- **Size cap:** 25 MB per file, applied to the listed size before downloading where the mailbox reports it, and to the actual bytes always.
- **Any type** is accepted.
- **Result:** a plain string, as every local tool returns: success names the full saved path and the size; refusals and failures start with `Error:` and never raise.

### Tool contract (both mailboxes)

Each save tool takes `message_id`, `attachment_id` and `file_name`, plus an optional `include_inline` (default false).

- `file_name` must equal the attachment's real file name exactly, or the save is refused. It exists so that the Approval prompt, which shows raw arguments (ADR-012), shows what is being saved. The tool checks the name again at save time rather than trusting what the Approval showed.
- An inline attachment is refused unless `include_inline` is true.
- Only file attachments are saved. Attached emails and cloud links are refused with a reason.

### Gmail

- `get_gmail_message` additionally lists the message's attachments (file name, size, attachment ID), walking the same MIME parts it already walks for the body. The attachment ID the model sees is the MIME part ID, because Gmail's own attachment ID changes on every fetch; the save finds the part again and uses that fetch's attachment ID. A part is inline when its `Content-Disposition` is `inline`, or when it has no `Content-Disposition` and has a `Content-ID`; `Content-Disposition: attachment` is never inline (Gmail gives normal attachments a `Content-ID` too). Inline parts are left out unless an optional `include_inline` argument is true.
- A new local tool, `save_gmail_attachment`, fetches the bytes through the Gmail API's attachments endpoint using the library already in use, decodes them and applies the save rules into `gmail/`. The current OAuth scope (`gmail.modify`) already covers this, so no new login is needed.
- It is wrapped in `write_action(...)`, and it has a Fixture world stand-in with the same name and arguments, registered like the other Google stand-ins.

### Outlook

- The model-facing tool is `ms365_save_attachment`, a wrapper on the agent side over the pinned server's `download-bytes-to-file` (ADR-005: the Outlook login stays inside the server). It is classified as a Write action.
- The wrapper:
  1. looks up the attachment with the server's `list-mail-attachments` and checks `file_name`, `isInline`, the attachment type and the listed size;
  2. calls `download-bytes-to-file` with the message's attachment `$value` path and a unique temporary name inside `outlook/`, because the server refuses to write over an existing file and so can't compare first;
  3. applies the duplicate and clash rules: deletes the temporary file on an identical match, otherwise renames it to the chosen name.
- `download-bytes-to-file` is added to what the server enables. It is a GET, so it asks for no new Graph scope and no Mail.Send. It is **never** bound to the model: the loader exposes the wrapper in its place, by name. The raw tool keeps its current status in the code: excluded from the read allowlist, so it would be a Write action anyway.
- `list-mail-attachments` stays a read and is not wrapped. It shows `isInline` on each attachment, so for Outlook "hidden by default" is enforced by the save tool's refusal of inline attachments, not by filtering the list.

### Classification and Approval

- Both save tools are Write actions (ADR-010). That gives the Approval and no automatic retry. The glossary's **Write action** entry now covers changes "in an external system or on the owner's computer".
- The Approval step and the graph stay generic: no mailbox-specific logic is added to them (ADR-012's reasoning).

### Prompts

- Every prompt version is rewritten as its full text. V3 and V4 must come out byte-for-byte identical; the released-prompt hash test proves it. Note that V4 is currently V2 plus extra text, not V3 plus extra text, and flattening must keep that.
- A new `v5` is V4's full text with one change: the default data folder line names `~/Downloads/personal_agent` instead of `~/Downloads/Personal`. Nothing else is added: the save tools' descriptions and their returned paths tell the model where saved attachments go. `v5` becomes the default prompt version.

### Fixture world

- Seed one personal Gmail message with a PDF attachment and an inline logo. The seeded "no personal mail has attachments" rule in the Gmail stand-in's search becomes data-driven, so a `has:attachment` query finds it.
- Give the seeded Outlook message that already has `hasAttachments: true` a real PDF attachment and an inline logo, served by `list-mail-attachments`.
- Emulate `download-bytes-to-file` in the fake MS365 server. It writes the seeded bytes and honours the real server's two rules: the path must be absolute, and an existing file is never overwritten.

### Evals

Three new scenarios, graded on outcomes:

1. Save a Gmail attachment, approved: the file exists in `gmail/` with the seeded bytes.
2. Save an Outlook attachment, rejected: nothing is written in the agent folder.
3. Outlook email to save to Informer upload, both approved: the file is in `outlook/`, and the fake Informer recorded exactly that file's bytes. The run needs two Approvals.

The eval harness points the agent folder at the run's working directory. Outcome grading reads the agent folder alongside the existing upload log.

## Testing Decisions

A good test exercises behaviour through the highest available seam and asserts on what the owner would see: the files on disk, the string returned to the model, whether the run paused for Approval. It doesn't assert on internal helpers or call sequences. All tests run against the Fixture world (ADR-011), with the agent folder in a temporary directory.

- **The tool seam (main):** the tools exactly as `load_all_tools(fixtures=True)` returns them, invoked directly. Test for both mailboxes:
  - writes stay inside that mailbox's own subfolder, and a name that tries to escape it (e.g. `../x.pdf`) still lands inside;
  - `(1)`/`(2)` on a clash with different contents;
  - an identical repeat writes nothing and returns the existing path;
  - an existing file is never overwritten;
  - a `file_name` mismatch is refused;
  - the 25 MB cap;
  - inline attachments are refused without `include_inline` and saved with it;
  - folders are created on first save;
  - `get_gmail_message` lists attachments and hides inline ones;
  - the raw `download-bytes-to-file` is not among the bound tools, and `ms365_save_attachment` is.

  Prior art: the MS365 Draft tests and the Fixture world Informer upload tests.
- **The Approval seam:** the existing classification tests already require every bound tool to be read-classified or gated by Approval, and they pick the new tools up automatically. Add one explicit test per mailbox: the save pauses for Approval, and a reject writes nothing. Prior art: the Write action classification tests and the Draft reject test.
- **The prompt seam:** the existing released-prompt hash test pins V3 and V4. Flattening must leave those hashes untouched. Add `v5` as a new line and never edit an existing line. Prior art: that test, and the test that unknown prompt versions are refused.
- **The Fixture world:** the emulated `download-bytes-to-file` refuses a relative path and an existing file. Prior art: the Fixture world MS365 tests.
- **The eval seam:** the outcome scoring for the three scenarios, with a unit test like the existing upload-outcome tests.

## Out of Scope

- **Prompt injection through email and file contents.** For example, an email instructing the agent to search other mail and put the results in a `web_search` query, which is a read and so runs without Approval. This is a separate ticket.
- Restricting `read_file`, `list_directory` or the Informer upload to the agent folder.
- Changing the Approval step to look up and display attachment details.
- Saving from other sources (web pages, Informer documents, OneDrive or SharePoint files).
- Attached emails (Outlook item attachments, Gmail `message/rfc822` parts) and cloud-link attachments.
- Exposing the server's `download-bytes-to-file` directly, or any other new Outlook write.
- Bulk "save every attachment in this folder" operations beyond what repeated single saves in one Approval already give.
- Changing the `download-bytes` read tool, which returns base64 bytes to the model and is already exposed.

## Further Notes

- The prompt still calls the folder line "default data folder". `v5` changes only the path, on purpose, to keep the text diff to one line.
- The real Outlook path cannot be exercised by tests (ADR-011). The first real save is a manual check. It should confirm that the pinned server's `download-bytes-to-file` accepts the attachment `$value` path, and that an Outlook login with the existing scopes is enough.
- Records from this session: ADR-015 (the Outlook save wrapper) and the separate prompt-injection ticket in `.scratch/email-prompt-injection/`.
