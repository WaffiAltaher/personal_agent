# 14: Generation metrics + efficiency + Langfuse tagging

**What to build:**
- Eval runs also score answer quality with RAGAS: faithfulness, answer relevancy, context precision and recall, using tool outputs as the contexts. A judge model is configured separately from the model under test.
- Each run records tokens, cost and latency.
- Langfuse traces are tagged with the model, prompt version, scenario and eval-run identifiers.

**Blocked by:** 13

**Status:** resolved

- [x] RAGAS integrated with a configurable judge model
- [x] Tokens, cost and latency per scenario run in the results JSON and report
- [x] Langfuse tags applied on eval runs
- [x] Tested with scripted model and judge; no network access needed

## Comments

- RAGAS 0.4.3 "collections" metrics (Faithfulness, AnswerRelevancy, ContextPrecision, ContextRecall) in `src/agent/evals/generation.py`. The judge is any LangChain chat model adapted by `ChatModelJudge` (RAGAS prompts carry their JSON schema; the reply text is parsed), so tests run the real metrics on a scripted judge. Contexts = successful tool outputs; reference = expected facts. Unscorable metrics are None with a reason in `generation.notes`. `RAGAS_DO_NOT_TRACK=true` is set by default (no telemetry).
- ragas 0.4.3 needs `langchain-community<0.4.2` (0.4.2 removed `chat_models.vertexai`); langchain-core stays 1.6.7.
- Judge: `--judge-model` > `EVAL_JUDGE_MODEL` > model under test (warning printed, flagged in the report). `--no-ragas` skips it. Answer relevancy embeds with `chroma_embedding_model` (Google).
- Cost: dated price table `src/agent/evals/pricing.py` (Gemini 3.8 Flash incl. the 2027-01-01 doubling; Claude Sonnet 5.5), sources cited; unknown model ⇒ null. Usage via `UsageMetadataCallbackHandler`. Judge calls are not counted in the run's tokens.
- Langfuse: `agent.tracing.langfuse_trace` — one trace per scenario run (resumes included), tags `eval`, `model:…`, `prompt:…`, `scenario:…`, `eval-run:…`, same as metadata; session = eval-run id; `RunResult.trace_id` recorded. `langfuse_spans` fixture moved to `tests/conftest.py`.
