# 02: MS365 stand-in records `send-shared-mailbox-mail`

**Type:** task

**What to build:** The Fixture world's MS365 stand-in (`fixture_world.ms365`) gains `send-shared-mailbox-mail`, with the real tool's argument shape at the pinned `@softeria/ms-365-mcp-server@0.159.1` (Graph `POST /users/{user-id}/sendMail`: the sending mailbox as `user-id`, and `body.Message` with `subject`, `body`, `toRecipients`, `ccRecipients`, `bccRecipients`, `attachments`, plus `SaveToSentItems`). It records every call as a JSON line in a file named by a new `FIXTURE_WORLD_MS365_*` variable, as the Draft tools do, and offers a helper to read the sent messages back. Its existing failure modes (logged out, transient, throttled, …) apply to it, and a new switch fails only the send. The agent's own MS365 tool policy is unchanged: the tool is never exposed to the model, and a test pins that.

**Blocked by:** None (can start immediately)

**Status:** resolved

- [x] Calling the tool records one entry with sender, recipients, CC, BCC, subject, body and attachments (name, content type, decoded bytes available through the helper)
- [x] The argument shape matches the pinned server's schema: check it against the real server's tool listing, not from memory
- [x] The logged-out and transient failure modes make the send fail as the real server reports it, recording no message
- [x] The send-only failure switch fails the send without affecting reads or Drafts
- [x] A test pins that `send-shared-mailbox-mail` (and `send-mail`) are not in the agent's `EXPOSED_TOOLS` or `ENABLED_TOOLS`

Spec: `../spec.md` (Fixture world and evals). ADR-019.

## Comments

- Built `send-shared-mailbox-mail` in `src/fixture_world/ms365.py`: arguments `userId`, `body` (`Message`, `SaveToSentItems`), `includeHeaders`, `excludeResponse`, `confirm`, as in the pinned server's listing; answers `{"message": "OK!"}`. Records accepted calls to the file named by `FIXTURE_WORLD_MS365_SENT`; `sent_messages(path)` reads them back (sender, to, cc, bcc, subject, body, attachments with decoded bytes, save_to_sent_items), `recorded_send_calls(path)` the raw calls. A `contentType` other than `text`/`html` and a body without `Message` are rejected, recording nothing. The existing failure modes apply through the shared wrapper; `FIXTURE_WORLD_MS365_SEND_FAILURE=transient` fails only the send (Graph 503).
- Tests: 9 in `tests/test_fixture_world_ms365_send.py` (recording, listing shape and annotations, two rejections, logged-out, transient and throttled, send-only switch, the policy pin). The listing and the policy-pin tests passed on first run (they pin behaviour the stand-in's framework and the unchanged policy already gave); the rest were red first.
