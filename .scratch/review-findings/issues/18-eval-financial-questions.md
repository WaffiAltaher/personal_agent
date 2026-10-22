# 18: Eval scenarios: financial questions

**Type:** task

**Model:** Composer 2.5

**Blocked by:** 14

**Status:** resolved

**Closes:** (evals decision, group 1)

**What to build:** Eval scenarios that ask for Revenue and VAT to pay ("What was revenue in Q2?", "How much VAT do I owe for Q3?", one sub-range of periods, one negative VAT quarter) pass only with the exact seeded amount in the answer and the right tool called.

- [x] Scenarios added and validated by the dataset checks (their facts exist in the Fixture world)
- [x] A scripted run that calls the right tool and quotes the amount passes; one that quotes a rounded amount fails
- [x] Killing test `k61` (facts match regardless of case) added and passing

Spec: `../spec.md`. Decisions: `../findings.md` ("Decisions taken").

## Comments

Four finance eval scenarios (Q2 revenue, Q3 VAT, periods 1–2 revenue, negative Q3 2025 VAT) with exact seeded amounts, `informer_revenue` / `informer_vat_position` required and trial balance forbidden. Added `test_eval_financial_scenarios.py` and killing test k61; dataset version `2026-10-22.2`.
