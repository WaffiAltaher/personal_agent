# 05: Only "approve" approves

**Type:** task

**Model:** Haiku

**Blocked by:** None (can start immediately)

**Status:** resolved

**Closes:** M11 (k11)

**What to build:** In the human review step, an Approval is approved only by the exact decision "approve". Every other value ("reject", "no", empty, None, a typo) rejects. Today anything except "reject" approves: it fails open.

- [ ] The Track B killing test `k11_anything_but_approve_rejects` is added to the suite and passes
- [ ] No other behaviour of the review step changes in this ticket

## Notes for the implementer

Keep the change minimal: ticket 09 reworks what a rejection does.

Spec: `../spec.md`. Decisions: `../findings.md` ("Decisions taken").

## Comments

- Resolved without a production change. `human_review_node` already approves only on `decision == "approve"` (in `src/agent/graph.py` since 754e4795, 2026-04-18), so the "fails open" premise did not hold on `feat/review-findings`. Added `tests/test_k11_anything_but_approve_rejects.py` (copy of `k11_anything_but_approve_rejects`, renamed with a `test_` prefix so pytest collects it). It passes on the branch. A temporary fail-open mutant (`!= "reject"`) makes all three cases fail; the mutant was reverted and not committed.
