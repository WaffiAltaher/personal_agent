# 05: Setup wizard step and docs for the two addresses

**Type:** task

**What to build:** `scripts/setup_wizard.sh` gains an optional Informer step that asks for the Informer incoming address and the Invoice mailbox and writes `INFORMER_INCOMING_ADDRESS` and `INFORMER_INVOICE_MAILBOX` to `.env`. It says the incoming address works like a write key to the books and must not be shared or committed, and opens Informer's e-mail settings page (`https://app.informer.eu/settings/email/`). `CLAUDE.md` documents the two settings and that uploads appear only when they are set.

**Blocked by:** 03

**Status:** resolved

- [x] The wizard step is skippable and writes or replaces only those two lines in `.env`
- [x] `CLAUDE.md` lists the two settings under the optional settings
- [x] Neither address appears in any tracked file

Spec: `../spec.md` (Setup and docs).

## Comments

- 2026-11-20 (claude): Added stage 5 "Informer: e-mail upload of Purchase invoices (optional)" to `scripts/setup_wizard.sh` (later stages renumbered, `TOTAL_STAGES=11`). A `y/N` gate skips it; otherwise it opens `https://app.informer.eu/settings/email/`, warns the incoming address is a write key (hidden input, never echoed), asks for the Invoice mailbox, and writes both lines with `write_env` only when both are non-empty. `CLAUDE.md` lists both settings under the optional ones. No address is in any tracked file (tests use `.example` addresses). Tests: `tests/test_setup_wizard.py` (5), running the script with stand-in tools on PATH and a temp `ENV_FILE`. Suite: 724 passed, 6 deselected.
