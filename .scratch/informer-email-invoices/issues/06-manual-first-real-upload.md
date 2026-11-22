# 06: [manual] Owner's first real upload by e-mail

**Type:** manual

**What to build:** The owner sets the two addresses in `.env` (or through the wizard), puts a real Purchase invoice that needs booking anyway in `~/Downloads`, asks the agent to upload it, and approves. Record the request, what was sent and what the accountant sees, as ticket 02 of `review-findings` recorded the v1 probe. Findings become new tickets.

**Blocked by:** 01, 04, 05

**Status:** ready-for-human

- [ ] The agent checks the file first and reports its name, folder and size
- [ ] After approval, the answer says the invoice was sent to Informer
- [ ] The message is in the Invoice mailbox's Sent Items: one PDF, the fixed subject and body, only the Informer incoming address as recipient
- [ ] The invoice appears in Informer (Purchase invoices, or the Inbox if it is on), marked "OCR" next to "To process"
- [ ] The accountant can book it normally
- [ ] Asking to upload the same file again is refused with the earlier date
- [ ] The result is recorded under a `## Upload record` heading in this file

Spec: `../spec.md`. ADR-019.

## Comments
