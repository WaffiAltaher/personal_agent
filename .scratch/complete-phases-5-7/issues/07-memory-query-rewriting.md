# 07: Memory query rewriting

**What to build:** Memory search understands natural phrasing. Asking "what did I ask about invoices last week" finds runs that mention Informer or overdue invoices. A model call rewrites the request into a semantic query for semantic memory and keyword variants for episodic memory, then merges, deduplicates and ranks the results. If the rewriting step fails, search falls back to the literal query. Resolves the memory entry in `docs/known_issues.md`.

**Blocked by:** 02

**Status:** ready-for-agent

- [ ] Both memory retrieval tools use the rewriting step
- [ ] The rewriting model is a separate setting, defaulting to the agent's model
- [ ] Tests with a scripted rewriter: a paraphrase finds a run the literal query misses; a rewriter error falls back to the literal query
- [ ] The known-issues memory entry is removed
