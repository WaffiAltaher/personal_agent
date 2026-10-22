# 22: Prompt caching

**Type:** task

**Model:** Composer 2.5

**Blocked by:** 21 (serialise: graph state), 12

**Status:** ready-for-agent

**Closes:** B10, F1

**What to build:** Within a run, every model call starts with the identical tools-plus-system-prompt opening: the clock is read once when the run starts and kept in state, and the runtime context uses that value for every call; tools are bound sorted by name. For Anthropic models, the end of the tool definitions and the system prompt are marked cacheable. Cached input tokens are recorded separately in the run log and eval usage, and pricing applies the cached rate.

- [ ] Test: across all model calls in a multi-step run, the system message is byte-identical
- [ ] Test: tools are bound in name order whatever order the servers return them in
- [ ] Test: with an Anthropic model spec, the request marks the tools and system prompt cacheable; with Gemini, nothing is added
- [ ] Test: cached tokens from a scripted usage report are recorded and priced at the cached rate
- [ ] A resumed run keeps the original clock value

Spec: `../spec.md`. Decisions: `../findings.md` ("Decisions taken").
