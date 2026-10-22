# 12: Memory written only on Approval; an honest run log

**Type:** task

**Model:** Composer 2.5

**Blocked by:** 09

**Status:** ready-for-agent

**Closes:** M5, M6, B7 (decision (h), ADR-014)

**What to build:** Long-term (semantic) memory is written only through a new `remember` tool, classified as a Write action, so every memory is approved. Answers are never ingested automatically, and the interactions collection is removed. The run log records per run: the question, tools called, total usage summed over all model calls, cost in USD, and the outcome (completed, error, rejected; ticket 20 adds step limit). Errors writing the run log are logged, not swallowed.

- [ ] Test: `remember` pauses for Approval; approved, the memory is retrievable; rejected, nothing is stored
- [ ] Test: a completed run adds nothing to semantic memory
- [ ] Test: the run log's usage is the sum over all model calls in a multi-step run, not the last call's
- [ ] Test: a run whose Write action was rejected is logged with outcome "rejected"; a crashed run with "error"
- [ ] Test: a failing run-log write is logged as a warning and doesn't crash the run
- [ ] Cost uses the existing pricing table; if that means moving it out of the evals package, move it rather than import evals code into the agent

Spec: `../spec.md`. Decisions: `../findings.md` ("Decisions taken").
