# 07: Memory query rewriting

**What to build:** Memory search understands natural phrasing. Asking "what did I ask about invoices last week" finds runs that mention Informer or overdue invoices. A model call rewrites the request into a semantic query for semantic memory and keyword variants for episodic memory, then merges, deduplicates and ranks the results. If the rewriting step fails, search falls back to the literal query. Resolves the memory entry in `docs/known_issues.md`.

**Blocked by:** 02

**Status:** superseded

Superseded by review-findings ticket 25 (decision (g)): the hidden rewrite model call and `MEMORY_REWRITE_MODEL` were removed; the main agent writes episodic search terms and optional date bounds, and semantic queries, as tool arguments. Episodic search uses SQLite FTS5 (BM25) instead of LIKE plus rewrite keywords.

- [x] Both memory retrieval tools use the rewriting step *(removed in ticket 25)*
- [x] The rewriting model is a separate setting, defaulting to the agent's model *(removed in ticket 25)*
- [x] Tests with a scripted rewriter *(removed in ticket 25)*
- [x] The known-issues memory entry is removed *(ticket 25)*

## Comments

- Superseded 2026-10-22 by ticket 25 on branch `ticket/25-past-run-search`.
