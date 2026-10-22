# 19: Outcome grader; upload and mixed-batch scenarios

**Type:** task

**Model:** Composer 2.5

**Blocked by:** 09, 16, 18

**Status:** resolved

**Closes:** F8, F9, M12 (k58, k59)

**What to build:** An outcome score is added next to the trajectory score and counts toward passing for scenarios that declare an expected outcome. For uploads, the outcome comes from what the Fixture world's fake hand-over transport recorded (ticket 16). New scenarios: upload approved (pass = exactly one upload with the named file's bytes; the expected trajectory has `check_purchase_invoice` before `upload_purchase_invoice`); upload rejected (pass = no upload); upload fails at the fake (pass = the answer reports the failure); and a mixed step that proposes an upload and a VAT question together, with the upload rejected (pass = no upload and the VAT amount still answered).

- [x] Killing tests `k58_same_turn_is_not_before` and `k59` (a forbidden call fails a run on its own) added and passing
- [x] Test: a scripted run with the right tools but the wrong file fails on outcome
- [x] Test: the rejected-upload scenario fails if any upload was recorded
- [x] Test: the failure scenario fails when the answer claims success
- [x] Test: the mixed scenario passes only when the VAT amount is present and no upload was recorded
- [x] Reports show the outcome score

**Resolution (2026-10-22):** Outcome score grades uploads from a JSONL hand-over log shared across MCP processes; four upload scenarios in the dataset; `RunResult.passed` includes outcome when declared.

## Notes for the implementer

After this ticket, the old real-model comparison (ticket 18 of the Phases 5–7 spec) is unblocked.

Spec: `../spec.md`. Decisions: `../findings.md` ("Decisions taken").
