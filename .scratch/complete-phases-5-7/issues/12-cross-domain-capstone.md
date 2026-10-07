# 12: Cross-domain capstone + system prompt v3

**What to build:** The owner asks "which clients are overdue on payment, and draft reminder emails". The agent finds Overdue invoices in Informer and proposes one Payment reminder Draft per Client, listing each invoice's number, due date and Open amount. It pauses for approval, then creates the approved Drafts in Outlook. Clients without an email address in Informer are reported to the owner, not guessed. A new system prompt version adds:
- ITtopia context
- the glossary rules (Drafts only, never send)
- guidance for combining Informer and MS365
- an instruction to use MS365, not Gmail, for ITtopia work

The whole run is one Langfuse trace.

**Blocked by:** 05, 10, 11

**Status:** ready-for-agent

- [ ] New prompt version, tagged in Langfuse as today
- [ ] A seam-A test of the capstone against the Fixture world: one Draft per Client with the right invoices and amounts, recorded only after approval; Clients without an email address are reported; nothing is created when rejected
