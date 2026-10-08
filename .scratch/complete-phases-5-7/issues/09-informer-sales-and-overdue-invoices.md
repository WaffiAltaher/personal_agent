# 09: Informer: Sales invoices + Overdue invoices

**What to build:** The Informer server can list and get Sales invoices (filtered by status and Relation). A dedicated tool returns Overdue invoices as of a date (default today), grouped by Client with each Client's total Open amount. Overdue invoice and Client follow `GLOSSARY.md`. The server handles Informer's realities itself:
- paging, with a truncation notice when the page cap is hit
- staying at or under 60 requests per minute, and honouring the quota headers
- a clear error when the daily quota is exhausted
- transient failures raised in a form the agent's retry policy recognises
- money as exact decimal strings in EUR, dates in ISO format

**Blocked by:** 08

**Status:** resolved

- [x] The fake Informer API serves seeded Sales invoices with pagination and rate-limit headers, and can be switched to quota-exhausted and 5xx modes
- [x] Seam-B tests for the Overdue boundaries: due today (not overdue), Open amount zero (not overdue), partially paid and past due (overdue with the remaining amount)
- [x] Seam-B tests for pagination across pages, the truncation notice, rate limiting, quota exhaustion, transient errors, decimal and ISO formatting

## Comments

- Tools (all `readOnlyHint`), in `src/informer_mcp/sales.py`:
  - `list_sales_invoices(status=None, relation_id=None)` returns `{currency, invoices: [{id, number, relation_id, invoice_date, due_date, total_incl_vat, paid, open_amount, status, concept, payment_date}], truncated[, notice]}`.
  - `get_sales_invoice(invoice_id)` returns the same fields plus `total_excl_vat, vat, reference, reminder_status, last_reminder_date, url, lines`.
  - `list_overdue_invoices(as_of=None)` returns `{as_of, currency, total_open_amount, clients: [{relation_id, name, email, email_invoice, total_open_amount, invoices: [{id, number, invoice_date, due_date, days_overdue, total_incl_vat, open_amount}]}], truncated[, notice]}`. Clients are sorted by total, largest first.
  - Money is a 2-decimal string (EUR), and dates are ISO strings.
- `list_relations` now pages too, and adds `truncated`/`notice`.
- Overdue invoices are read with Informer's `filter=open`. The server then applies the glossary rule itself: Open amount > 0, Due date < as_of, concepts excluded. Assumption: Informer's `open` filter includes partially paid invoices. Check this against the real API in ticket 16.
- "Today" is Amsterdam's date unless `INFORMER_TODAY` is set. With the Fixture world, set `INFORMER_TODAY=2026-10-07` (`fixture_world.clock.SEED_TODAY`). The fake does not week-shift invoice dates the way the MS365 stand-in does; ticket 11 can align the two if needed. New settings: `INFORMER_PAGE_SIZE` (default 100) and `INFORMER_MAX_PAGES` (default 10).
- Transient failures (unreachable, timeout, 429 with daily quota left, 5xx) raise `InformerTransientError`, which subclasses `ConnectionError`. Over MCP only text travels: it starts with `TRANSIENT_ERROR_PREFIX` ("Transient Informer failure") and names the HTTP status. The adapter turns MCP `isError` results into error ToolMessages rather than exceptions. So the agent-side loader (ticket 06/11) has to map that prefix to a retryable exception for `_should_retry` to see it.
- An exhausted daily quota (429 with `X-DailyLimit-Remaining: 0`) is a permanent error that says retrying today won't help. I assumed Informer answers 429 here; the spec defines no response.
- Rate limiting uses a sliding window of 60 requests per 60 s, plus a full 60 s pause whenever `X-RateLimit-Remaining` hits 0. Tests inject `RateLimiter(clock=, sleep=)` through `create_server(settings, rate_limiter=)`.
- The fake API has new modes `Failure.QUOTA_EXHAUSTED` and `Failure.SERVER_ERROR`, plus `fail_after`, `spend(minute=, day=)`, a replaceable `clock` and a `requests` log.
