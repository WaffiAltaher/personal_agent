# 15: Throttling (429) in the fakes

**Type:** task

**Model:** Haiku

**Blocked by:** None (can start immediately)

**Status:** claimed

**Closes:** F5 (k31, k48)

**What to build:** The fake Informer API and the Microsoft 365 stand-in can be switched to answer with throttling (429), so retries are tested against the failure that actually happens in production.

- [ ] Killing tests `k31_per_minute_429_is_transient` and `k48_throttled_graph_call_is_transient` added and passing
- [ ] Each fake has a 429 mode next to its existing failure modes, used by at least one retry test

Spec: `../spec.md`. Decisions: `../findings.md` ("Decisions taken").
