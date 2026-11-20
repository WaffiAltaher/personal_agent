# 02: MS365 stand-in records `send-shared-mailbox-mail`

**Type:** task

**What to build:** The Fixture world's MS365 stand-in (`fixture_world.ms365`) gains `send-shared-mailbox-mail`, with the real tool's argument shape at the pinned `@softeria/ms-365-mcp-server@0.159.1` (Graph `POST /users/{user-id}/sendMail`: the sending mailbox as `user-id`, and `body.Message` with `subject`, `body`, `toRecipients`, `ccRecipients`, `bccRecipients`, `attachments`, plus `SaveToSentItems`). It records every call as a JSON line in a file named by a new `FIXTURE_WORLD_MS365_*` variable, as the Draft tools do, and offers a helper to read the sent messages back. Its existing failure modes (logged out, transient, throttled, …) apply to it, and a new switch fails only the send. The agent's own MS365 tool policy is unchanged: the tool is never exposed to the model, and a test pins that.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] Calling the tool records one entry with sender, recipients, CC, BCC, subject, body and attachments (name, content type, decoded bytes available through the helper)
- [ ] The argument shape matches the pinned server's schema: check it against the real server's tool listing, not from memory
- [ ] The logged-out and transient failure modes make the send fail as the real server reports it, recording no message
- [ ] The send-only failure switch fails the send without affecting reads or Drafts
- [ ] A test pins that `send-shared-mailbox-mail` (and `send-mail`) are not in the agent's `EXPOSED_TOOLS` or `ENABLED_TOOLS`

Spec: `../spec.md` (Fixture world and evals). ADR-019.

## Comments
