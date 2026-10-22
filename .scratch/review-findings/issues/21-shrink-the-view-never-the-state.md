# 21: Shrink the view, never the state

**Type:** task

**Model:** Composer 2.5

**Blocked by:** 20 (serialise: graph state)

**Status:** resolved

**Closes:** C1–C10, C11 (drops k23, k25, k90; ADR-013)

**What to build:** Context reduction no longer removes anything from state; the trim and its message-removal path are deleted. Before each model call, the token count is the previous call's reported input tokens plus an estimate (four characters per token) of messages added since (first call: estimate everything, including system prompt and tool definitions). Above 100k, tool results from earlier steps are replaced in the model's view, oldest first, by a stub giving their approximate size and saying the tool can be called again, until under 50k. User messages and every model message stay; every tool call keeps an answer. A tool result over 20k tokens is truncated where tools return, with a marker. The warning threshold setting goes away. Retrieved memory is limited to top-k chunks within the memory budget (10k). Stale docstrings about Gemini 2.0 and deferred integration are fixed.

- [x] Test: nothing is ever removed from state, however large the context
- [x] Test: above the threshold, the view keeps the first user message, has no unanswered tool call and is never empty
- [x] Test: one 300k-token tool result is truncated with a marker and the run continues
- [x] Test: after a reduction the view is under 50k, and the next step doesn't reduce again
- [x] Test: the count includes tool-call arguments and the system prompt and tool definitions
- [x] Test: memory retrieval stops at the budget
- [x] Old trim tests replaced; k23, k25, k90 not added

## Notes for the implementer

Trap: reduce only in the view passed to the model, never through a state update. Thresholds come from settings; tests should use small non-default thresholds.

Spec: `../spec.md`. Decisions: `../findings.md` ("Decisions taken").

## Comments

Implemented `context_view.py` (view-only stubs, token estimate, per-result cap), removed state trim/settings, wired graph agent node and memory budget trimming; merged `feat/review-findings`.
