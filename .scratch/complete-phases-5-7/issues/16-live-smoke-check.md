# 16: Live smoke check (read-only)

**What to build:** A read-only check against the real services confirms that MS365 (mail, calendar, contacts reads) and Informer (Relations, Sales invoices) connect with the owner's credentials. It never creates a Draft. It is marked as a live test and skipped by default. If the MS365 login is missing or the keychain prompt blocks a headless run, it reports "blocked" with the reason instead of hanging.

**Blocked by:** 01, 05, 11

**Status:** ready-for-agent

- [ ] Live-marked tests, skipped by default and run explicitly
- [ ] Results recorded under `## Comments` in this ticket
