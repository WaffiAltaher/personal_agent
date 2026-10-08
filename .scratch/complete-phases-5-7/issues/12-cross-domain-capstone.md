# 12: Cross-domain capstone + system prompt v3

**What to build:** The owner asks "which clients are overdue on payment, and draft reminder emails". The agent finds Overdue invoices in Informer and proposes one Payment reminder Draft per Client, listing each invoice's number, due date and Open amount. It pauses for approval, then creates the approved Drafts in Outlook. Clients without an email address in Informer are reported to the owner, not guessed. A new system prompt version adds:
- ITtopia context
- the glossary rules (Drafts only, never send)
- guidance for combining Informer and MS365
- an instruction to use MS365, not Gmail, for ITtopia work

The whole run is one Langfuse trace.

**Blocked by:** 05, 10, 11

**Status:** resolved

- [x] New prompt version, tagged in Langfuse as today
- [x] A seam-A test of the capstone against the Fixture world: one Draft per Client with the right invoices and amounts, recorded only after approval; Clients without an email address are reported; nothing is created when rejected

## Comments

- 2026-10-07: Prompt `v3` (`agent.prompts.PROMPT_V3`, built on v2) is now the default `PROMPT_VERSION`; the CLI already tags each run's single Langfuse trace with `prompt-version` metadata, and resumes after approval reuse the same handler, so the capstone stays one trace. v3 adds a rule the glossary leaves open: a Payment reminder goes to the Client's invoice address (`email_invoice`), else its general `email`. The seed data already had what the test needs (Gouden Bol: 2 Overdue invoices incl. a partially paid one plus one due today; Van Dijk: 2 + a paid one; Noordzee Advies without email), so it is unchanged. `tests/test_capstone.py` runs the flow over real MCP; `ScriptedChatModel` now also accepts a reply that is a function of the messages shown, so the scripted reminders are composed from the Informer result the model actually saw and asserted against seeded literals.
