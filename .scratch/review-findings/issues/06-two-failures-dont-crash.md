# 06: Two failures in one step don't crash the run

**Type:** task

**Model:** Haiku

**Blocked by:** None (can start immediately)

**Status:** claimed

**Closes:** M3 (k03)

**What to build:** When two tools fail in the same step, both errors are recorded and the run continues. The killing test proves the graph state's error list keeps its merging reducer, which is what prevents the crash.

- [ ] The Track B killing test `k03_two_failures_in_one_batch` is added to the suite and passes on the real code
- [ ] Temporarily removing the reducer makes it fail (check by hand; don't commit the mutant)

Spec: `../spec.md`. Decisions: `../findings.md` ("Decisions taken").
