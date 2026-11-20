# 07: [open] Verify that the owner's login can no longer send as the owner

**Type:** manual

**What to build:** On 2026-11-20 the pinned MS365 server's `send-mail` sent two test messages as the owner (Graph 202, request ids `6d60d47b-e136-4e69-817f-e5d5ebd74c1a` and `a0869949-ecc6-4cbb-9968-dd0ee8a431e9`), the second after `Mail.Send` had been removed from the app registration but before the consent grant was edited. Confirm that, with `Mail.Send` gone from the consent grant and after `--logout` and `--login`, the token can no longer send from the owner's own address. Do it with one probe: the pinned server with only `send-mail` enabled, sending one message to the owner's Gmail.

Deferred by the owner on 2026-11-20, to pick up later. The design (ADR-019) doesn't depend on the result. It decides how much protection removing `Mail.Send` gives.

**Blocked by:** None

**Status:** ready-for-human

- [ ] The consent grant (Graph `oauth2PermissionGrants` for the app's service principal) no longer contains `Mail.Send`
- [ ] After logging out and in again, the probe gets 403: the token can't send as the owner
- [ ] If it still sends, ADR-019's consequence is updated: the mail-flow rule and the exact pin are the only limits on sending
- [ ] The result is recorded under a `## Probe record` heading in this file

Spec: `../spec.md` (Tenant setup). ADR-019.

## Comments
