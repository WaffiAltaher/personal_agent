# 05: Setup wizard step and docs for the two addresses

**Type:** task

**What to build:** `scripts/setup_wizard.sh` gains an optional Informer step that asks for the Informer incoming address and the Invoice mailbox and writes `INFORMER_INCOMING_ADDRESS` and `INFORMER_INVOICE_MAILBOX` to `.env`. It says the incoming address works like a write key to the books and must not be shared or committed, and opens Informer's e-mail settings page (`https://app.informer.eu/settings/email/`). `CLAUDE.md` documents the two settings and that uploads appear only when they are set.

**Blocked by:** 03

**Status:** ready-for-agent

- [ ] The wizard step is skippable and writes or replaces only those two lines in `.env`
- [ ] `CLAUDE.md` lists the two settings under the optional settings
- [ ] Neither address appears in any tracked file

Spec: `../spec.md` (Setup and docs).

## Comments
