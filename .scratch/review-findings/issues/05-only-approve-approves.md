# 05: Only "approve" approves

**Type:** task

**Model:** Haiku

**Blocked by:** None (can start immediately)

**Status:** claimed

**Closes:** M11 (k11)

**What to build:** In the human review step, an Approval is approved only by the exact decision "approve". Every other value ("reject", "no", empty, None, a typo) rejects. Today anything except "reject" approves: it fails open.

- [ ] The Track B killing test `k11_anything_but_approve_rejects` is added to the suite and passes
- [ ] No other behaviour of the review step changes in this ticket

## Notes for the implementer

Keep the change minimal: ticket 09 reworks what a rejection does.

Spec: `../spec.md`. Decisions: `../findings.md` ("Decisions taken").
