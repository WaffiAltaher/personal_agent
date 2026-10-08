# 16: Live smoke check (read-only)

**What to build:** A read-only check against the real services confirms that MS365 (mail, calendar, contacts reads) and Informer (Relations, Sales invoices) connect with the owner's credentials. It never creates a Draft. It is marked as a live test and skipped by default. If the MS365 login is missing or the keychain prompt blocks a headless run, it reports "blocked" with the reason instead of hanging.

**Blocked by:** 01, 05, 11

**Status:** resolved

- [x] Live-marked tests, skipped by default and run explicitly
- [x] Results recorded under `## Comments` in this ticket

## Comments

- 2026-10-08: `pytest -m live` passed (13.5s) on `feat/complete-phases-5-7`. MS365 mail, calendar, and contacts reads returned HTTP 200. Informer Relations and Sales invoices returned collections. No Draft tool was called. The default suite deselects this test (`226 passed, 1 deselected` before this comment).
- The first live run failed on `informer_list_relations`: Informer answered HTTP 400 "No records found" for `page=1`. The live API numbers pages from 0 and sends `pagination.prev` / `pagination.next`, not `total` / `pages`. `get_pages`, Relation lookup, and the Fixture world fake now follow that. An empty first page (that same 400) is an empty collection. Re-run passed.
