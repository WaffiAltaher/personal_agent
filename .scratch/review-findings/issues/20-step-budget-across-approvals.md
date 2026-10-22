# 20: Step budget across Approvals

**Type:** task

**Model:** Composer 2.5

**Blocked by:** 09 (serialise: graph state)

**Status:** resolved

**Closes:** B3 (k18, k65 rewritten)

**What to build:** A model-call counter lives in the graph state for the run. Each model call increments it; a new user message resets it; resuming after an Approval does not. At the configured maximum (the existing max-iterations setting, default 10; today unused), the run ends with an answer saying it hit the step limit. The framework's recursion limit stays only as a backstop. The eval harness uses the same mechanism and records such runs as step-limit results, and the run log gets outcome "step limit".

- [x] Test: a scripted model that always asks for a tool stops after exactly the configured number of model calls with the step-limit answer
- [x] Test: approving three times in one run doesn't reset the count
- [x] Test: a new user message starts with a fresh count
- [x] k18 and k65 rewritten against this limit (k65 must not use the default value) and passing
- [x] The run log records "step limit" for such runs

## Notes for the implementer

Trap: a test that only uses the default maximum can't tell "the configured maximum" from "always 10"; set a non-default value.

Spec: `../spec.md`. Decisions: `../findings.md` ("Decisions taken").
