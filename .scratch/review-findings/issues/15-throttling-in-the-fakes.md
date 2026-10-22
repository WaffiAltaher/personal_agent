# 15: Throttling (429) in the fakes

**Type:** task

**Model:** Haiku

**Blocked by:** None (can start immediately)

**Status:** resolved

**Closes:** F5 (k31, k48)

**What to build:** The fake Informer API and the Microsoft 365 stand-in can be switched to answer with throttling (429), so retries are tested against the failure that actually happens in production.

- [x] Killing tests `k31_per_minute_429_is_transient` and `k48_throttled_graph_call_is_transient` added and passing
- [x] Each fake has a 429 mode next to its existing failure modes, used by at least one retry test

Spec: `../spec.md`. Decisions: `../findings.md` ("Decisions taken").

## Comments

- 2026-10-22: Added `throttled` (429) to the fake Informer API (per-minute; the daily quota stays permanent) and to the MS365 stand-in (Graph 429). Retry tests: `test_throttled_read_tool_is_retried` and `test_persistent_throttling_reaches_the_model_after_the_retries` (MS365), `test_throttled_informer_call_is_retried_on_a_read_tool` (Informer). k31 and k48 landed. Full suite: 250 passed after merging `feat/review-findings`.
