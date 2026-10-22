# 18: Eval scenarios: financial questions

**Type:** task

**Model:** Composer 2.5

**Blocked by:** 14

**Status:** ready-for-agent

**Closes:** (evals decision, group 1)

**What to build:** Eval scenarios that ask for Revenue and VAT to pay ("What was revenue in Q2?", "How much VAT do I owe for Q3?", one sub-range of periods, one negative VAT quarter) pass only with the exact seeded amount in the answer and the right tool called.

- [ ] Scenarios added and validated by the dataset checks (their facts exist in the Fixture world)
- [ ] A scripted run that calls the right tool and quotes the amount passes; one that quotes a rounded amount fails
- [ ] Killing test `k61` (facts match regardless of case) added and passing

Spec: `../spec.md`. Decisions: `../findings.md` ("Decisions taken").
