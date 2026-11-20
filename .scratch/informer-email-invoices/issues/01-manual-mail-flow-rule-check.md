# 01: [manual] Check that the Invoice mailbox can send only to the Informer incoming address

**Type:** manual

**What to build:** One real send from the Invoice mailbox to an address other than the Informer incoming address, for example the owner's Gmail, to prove that the Exchange mail-flow rule enforces the recipient lock. This can be done in Outlook on the web (choosing the Invoice mailbox as From), or by running the pinned MS365 server's `send-shared-mailbox-mail` once with the owner's go-ahead. Record the result below.

**Blocked by:** None (can start immediately)

**Status:** ready-for-human

- [ ] The message is rejected by Exchange, and a bounce lands in the Invoice mailbox (record its text)
- [ ] If it is delivered instead, the mail-flow rule is fixed before ticket 06
- [ ] The result is recorded under a `## Check record` heading in this file

Spec: `../spec.md` (Tenant setup). ADR-019.

## Comments
