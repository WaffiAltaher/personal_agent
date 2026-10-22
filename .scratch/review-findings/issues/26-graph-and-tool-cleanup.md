# 26: Graph and tool cleanup

**Type:** task

**Model:** Haiku

**Blocked by:** 22 (serialise: graph state)

**Status:** claimed

**Closes:** B4, E3, X1, X2

**What to build:** Small corrections: the fallback's tool message for an unexpected crash has error status and describes the actual failure instead of always saying "try again later"; tool schemas are normalised when bound (`$schema` and `additionalProperties` dropped, with a comment that the MS365 download tool's `false` is dropped deliberately), so Gemini stops logging ~70 warnings per run; the graph state comment says messages are merged by ID, not appended.

- [ ] Killing test `k07_fallback_catches_a_crash` added and passing
- [ ] Test: the fallback message has error status and contains the failure's text
- [ ] Test: no bound tool schema contains `$schema` or `additionalProperties`
- [ ] The state comment and the budget docstring describe the code as it is

Spec: `../spec.md`. Decisions: `../findings.md` ("Decisions taken").
