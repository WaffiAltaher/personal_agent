# 12: Memory written only on Approval; an honest run log

**Type:** task

**Model:** Composer 2.5

**Blocked by:** 09

**Status:** resolved

**Closes:** M5, M6, B7 (decision (h), ADR-014)

**What to build:** Long-term (semantic) memory is written only through a new `remember` tool, classified as a Write action, so every memory is approved. Answers are never ingested automatically, and the interactions collection is removed. The run log records per run: the question, tools called, total usage summed over all model calls, cost in USD, and the outcome (completed, error, rejected; ticket 20 adds step limit). Errors writing the run log are logged, not swallowed.

- [x] Test: `remember` pauses for Approval; approved, the memory is retrievable; rejected, nothing is stored
- [x] Test: a completed run adds nothing to semantic memory
- [x] Test: the run log's usage is the sum over all model calls in a multi-step run, not the last call's
- [x] Test: a run whose Write action was rejected is logged with outcome "rejected"; a crashed run with "error"
- [x] Test: a failing run-log write is logged as a warning and doesn't crash the run
- [x] Cost uses the existing pricing table; if that means moving it out of the evals package, move it rather than import evals code into the agent

Spec: `../spec.md`. Decisions: `../findings.md` ("Decisions taken").

## Comments

`remember` is a Write action; semantic store uses a `memories` collection (no auto-ingest). Run logging lives in `agent/memory/run_log.py` with pricing in `agent/pricing.py`. Covered by `tests/test_memory_run_log.py`; 319 tests passed after merge with `feat/review-findings`.
