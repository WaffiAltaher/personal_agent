# 17: Manual live path testing

**What to build:** A person walks every path the model can take, through the CLI against the real services, and confirms each interface actually works. This is a human pass: not the Fixture world (`--fixtures`), and not the automated read-only smoke check in ticket 16. Run the four ITtopia workflows — inbox triage, overdue-invoice reminders, finance questions, and web research — plus the remaining interfaces the model can call: local files, Gmail and Google Calendar, and memory. Exercise both configured models (`google_genai:gemini-3.8-flash` and `anthropic:claude-sonnet-5-5`). On every Write action (an Outlook Draft and a Gmail draft), confirm the run pauses for approval, an approval creates only that Draft, and a rejection creates nothing.

Record every problem in `.scratch/review-findings/findings.md` as it is found: what was asked, which model and interface, what happened, and what should have happened. Do not open a ticket per finding during the walk. When the walk is finished, translate that register into separate tickets, one per finding, under `.scratch/review-findings/`.

**Blocked by:** 01

**Status:** resolved

- [x] Each of the four workflows returns a real result on both models
- [x] Every interface answers: MS365 (mail, calendar, contacts, and both Draft tools), Informer (Relations, Sales invoices, Overdue invoices, trial balance), Gmail, Google Calendar, local files, web search, and memory
- [x] Approval gates every Write action; a rejection creates nothing
- [x] Each problem found is added to `.scratch/review-findings/findings.md`
- [ ] At the end, `.scratch/review-findings/findings.md` is translated into separate tickets
