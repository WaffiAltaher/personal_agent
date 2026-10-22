# 26: Graph and tool cleanup

**Type:** task

**Model:** Haiku

**Blocked by:** 22 (serialise: graph state)

**Status:** resolved

**Closes:** B4, E3, X1, X2

**What to build:** Small corrections: the fallback's tool message for an unexpected crash has error status and describes the actual failure instead of always saying "try again later"; tool schemas are normalised when bound (`$schema` and `additionalProperties` dropped, with a comment that the MS365 download tool's `false` is dropped deliberately), so Gemini stops logging ~70 warnings per run; the graph state comment says messages are merged by ID, not appended.

- [x] Killing test `k07_fallback_catches_a_crash` added and passing
- [x] Test: the fallback message has error status and contains the failure's text
- [x] Test: no bound tool schema contains `$schema` or `additionalProperties`
- [x] The state comment and the budget docstring describe the code as it is

Spec: `../spec.md`. Decisions: `../findings.md` ("Decisions taken").

## Comments

Fallback ToolMessage now has `status="error"` and `name`, and says the outcome is unknown instead of "try again later". `bind_agent_tools` binds normalised tool specs: `$schema` and `additionalProperties` are dropped at every depth, property names are kept. Gemini schema warnings for the probe tools dropped from 4 to 0. The MS365 download tool's `false` is dropped on purpose. The state comment now says messages merge by ID; the budget module docstring says the view is reduced and state is never trimmed. Killing test k07 copied verbatim, no adaptation needed.
