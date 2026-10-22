# 25: Past-run search the agent writes

**Type:** task

**Model:** Composer 2.5

**Blocked by:** 12, 19

**Status:** ready-for-agent

**Closes:** M2, M3, R1, R2, R3 (decision (g))

**What to build:** The hidden query-rewrite model call and its setting are deleted. The past-runs tool takes search terms plus optional start and end dates, written by the agent as tool arguments; the long-term memory tool takes a query the agent writes. Past runs are searched with SQLite full-text search ranked by relevance, filtered by date. An empty result says so plainly, so the agent can try other terms. Two eval scenarios: "what did I ask about VAT last week?", and one where the first search finds nothing and the agent must retry. The stale memory paragraph in the known-issues notes is removed and ticket 07 of the Phases 5–7 spec is marked superseded.

- [ ] Test: whole-word matching ("VAT" doesn't match "private") and relevance ranking
- [ ] Test: the date filter excludes runs outside the range
- [ ] Test: `%` and `_` in search terms are matched literally
- [ ] The rewrite module and its setting are gone; nothing references them
- [ ] Both eval scenarios added and passing with scripted runs
- [ ] Known-issues paragraph removed; old ticket 07 marked superseded

Spec: `../spec.md`. Decisions: `../findings.md` ("Decisions taken").
