# 07: Memory query rewriting

**What to build:** Memory search understands natural phrasing. Asking "what did I ask about invoices last week" finds runs that mention Informer or overdue invoices. A model call rewrites the request into a semantic query for semantic memory and keyword variants for episodic memory, then merges, deduplicates and ranks the results. If the rewriting step fails, search falls back to the literal query. Resolves the memory entry in `docs/known_issues.md`.

**Blocked by:** 02

**Status:** resolved

- [x] Both memory retrieval tools use the rewriting step
- [x] The rewriting model is a separate setting, defaulting to the agent's model
- [x] Tests with a scripted rewriter: a paraphrase finds a run the literal query misses; a rewriter error falls back to the literal query
- [ ] The known-issues memory entry is removed

## Comments

- `agent.memory.recall`: `rewrite_query` (JSON reply → semantic query + keywords; never raises, falls back to the literal request on model build/call/parse failure), `recall_runs` (literal + keyword variants, deduped, ranked by variants matched then recency), `recall_chunks` (literal + semantic query, deduped by content, best score). Both tools call these.
- New setting `MEMORY_REWRITE_MODEL` (`provider:model`, default unset → `MODEL_NAME`), built via `create_chat_model`.
- Tests: `tests/memory/test_recall.py` (scripted rewriter, temp stores, toy topic embeddings; no network).
- Open: removing the memory entry from `docs/known_issues.md` was blocked by a tool permission check in the implementer session; the owner needs to delete its first paragraph.
