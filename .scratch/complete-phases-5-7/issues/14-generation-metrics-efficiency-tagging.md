# 14: Generation metrics + efficiency + Langfuse tagging

**What to build:**
- Eval runs also score answer quality with RAGAS: faithfulness, answer relevancy, context precision and recall, using tool outputs as the contexts. A judge model is configured separately from the model under test.
- Each run records tokens, cost and latency.
- Langfuse traces are tagged with the model, prompt version, scenario and eval-run identifiers.

**Blocked by:** 13

**Status:** ready-for-agent

- [ ] RAGAS integrated with a configurable judge model
- [ ] Tokens, cost and latency per scenario run in the results JSON and report
- [ ] Langfuse tags applied on eval runs
- [ ] Tested with scripted model and judge; no network access needed
