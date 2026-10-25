# 05: [manual] First real Outlook and Gmail save

**What to build:** The owner confirms that the feature works against the real mailboxes, which the tests can't reach (ADR-011). Run the agent in real mode and save one real attachment from each mailbox. Record the results below.

**Blocked by:** 03

**Status:** ready-for-human

- [ ] Outlook: the pinned server's `download-bytes-to-file` accepts the attachment `$value` path with the existing Outlook login and scopes, and the file lands in `~/Downloads/personal_agent/outlook/` with the right contents
- [ ] Gmail: a save works with the existing Google token, with no new login prompted, and the file lands in `~/Downloads/personal_agent/gmail/`
- [ ] The Approval prompt shows each attachment's real file name
- [ ] Saving the same attachment again writes nothing and reports the existing path
- [ ] The results are recorded under a `## Record` heading in this file

Spec: `../spec.md` (Further Notes).
