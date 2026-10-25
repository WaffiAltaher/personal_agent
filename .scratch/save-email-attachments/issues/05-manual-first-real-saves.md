# 05: [manual] First real Outlook and Gmail save

**What to build:** The owner confirms that the feature works against the real mailboxes, which the tests can't reach (ADR-011). Run the agent in real mode and save one real attachment from each mailbox. Record the results below.

**Blocked by:** 03

**Status:** resolved

- [x] Outlook: the pinned server's `download-bytes-to-file` accepts the attachment `$value` path with the existing Outlook login and scopes, and the file lands in `~/Downloads/personal_agent/outlook/` with the right contents
- [x] Gmail: a save works with the existing Google token, with no new login prompted, and the file lands in `~/Downloads/personal_agent/gmail/`
- [x] The Approval prompt shows each attachment's real file name
- [x] Saving the same attachment again writes nothing and reports the existing path
- [x] The results are recorded under a `## Record` heading in this file

Spec: `../spec.md` (Further Notes).

Also confirm, from the build (only a real save can tell):
- [x] Gmail: the attachment ID shown by `get_gmail_message` (the MIME part ID) still saves after a fresh fetch, and a normal attachment sent from Gmail (which carries a `Content-ID`) is listed, not hidden as inline
- [x] Outlook: real file attachments carry `contentBytes` in the `list-mail-attachments` response, including large ones; an attached email is refused
- [x] Outlook: real Graph message IDs pass the server's plain-path check for `target`

## Record

Run by the owner on 2026-10-25 with `anthropic:claude-sonnet-5-5`, real mode, one save per mailbox.

- Outlook: a Centraal Beheer nota (139,169 bytes) from the ITtopia mailbox. The first attempts were refused because the real file name contains non-breaking spaces and the model sent plain spaces; fixed in `f0a3775` (names are compared and saved in a typeable form). After the fix: one Approval, the file landed in `~/Downloads/personal_agent/outlook/` with plain spaces, and it is a valid PDF. So `$value` is accepted as `target`, real Graph message IDs pass the server's path check, `contentBytes` is present for the file attachment, and the existing login and scopes are enough.
- Gmail: `Invoice-G8QTLYRH-0018.pdf` (34,394 bytes) landed in `~/Downloads/personal_agent/gmail/`, a valid PDF, with no new Google login. So the listed part ID still saves after a fresh fetch, and the attachment was listed, not hidden as inline.
- The Approval prompt showed the real file name for both mailboxes.
- A repeat save wrote nothing and reported the existing path. The owner found the one-line "not downloaded" answer easy to miss; fixed in `5881db0` (the result starts with a `NOT DOWNLOADED:` line, and the tool descriptions tell the model to lead its answer with it).
- Not checked live: refusing an attached email. Neither mailbox has one, so this is covered by Fixture world tests only.
- Observed: the Outlook file is saved `-rw-------` (the MS365 server's file mode); the Gmail file is `-rw-r--r--`. Left as is.
- Observed: after each refused save the model resent the identical call, costing three needless Approvals. That was triggered by the name bug, but the habit itself is worth its own ticket.
