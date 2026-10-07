# 09: Informer: Sales invoices + Overdue invoices

**What to build:** The Informer server can list and get Sales invoices (filtered by status and Relation). A dedicated tool returns Overdue invoices as of a date (default today), grouped by Client with each Client's total Open amount. Overdue invoice and Client follow `GLOSSARY.md`. The server handles Informer's realities itself:
- paging, with a truncation notice when the page cap is hit
- staying at or under 60 requests per minute, and honouring the quota headers
- a clear error when the daily quota is exhausted
- transient failures raised in a form the agent's retry policy recognises
- money as exact decimal strings in EUR, dates in ISO format

**Blocked by:** 08

**Status:** ready-for-agent

- [ ] The fake Informer API serves seeded Sales invoices with pagination and rate-limit headers, and can be switched to quota-exhausted and 5xx modes
- [ ] Seam-B tests for the Overdue boundaries: due today (not overdue), Open amount zero (not overdue), partially paid and past due (overdue with the remaining amount)
- [ ] Seam-B tests for pagination across pages, the truncation notice, rate limiting, quota exhaustion, transient errors, decimal and ISO formatting
