# 18: Real model-comparison run

**What to build:** Run the full scenario suite against the Fixture world with Gemini 3.8 Flash and Claude Sonnet 5.5, using the agreed number of repeats and a separate judge model. Generate the comparison report and commit the results JSON and the report.

**Blocked by:** 01, 15, 17

**Status:** ready-for-agent

- [ ] Both models run on the full suite, with traces visible in Langfuse
- [ ] Comparison report and raw results committed

## Owner follow-up

Written by ticket 15. Needs `GOOGLE_API_KEY` (Gemini, and the embeddings answer relevancy uses) and
`ANTHROPIC_API_KEY` in `.env`, and local Langfuse running (`http://localhost:3000`). No MS365 or
Informer credentials: the evals run against the Fixture world (pinned to 2026-10-07, seeded web search).

Both runs use the same judge model, which is neither model under test, so no model grades itself and
the RAGAS scores of the two runs are graded alike (`claude-opus-5-5` shares a family with Sonnet;
note that in the write-up). Three repeats per scenario (18 scenarios, 54 runs per model):

```bash
uv run python -m agent.evals --model google_genai:gemini-3.8-flash --judge-model anthropic:claude-opus-5-5 --repeats 3
uv run python -m agent.evals --model anthropic:claude-sonnet-5-5 --judge-model anthropic:claude-opus-5-5 --repeats 3
# each prints its results path: data/evals/<eval-run-id>.json (+ .md)
uv run python -m agent.evals compare data/evals/<gemini-eval-run-id>.json data/evals/<claude-eval-run-id>.json
# writes data/evals/compare-<gemini-eval-run-id>-vs-<claude-eval-run-id>.md
```

Commit the two results JSON files, their `.md` reports and the `compare-*.md` report. The comparison
report warns at the top if the runs are not comparable (dataset or prompt version differ) or if a
model graded its own answers; neither should appear. Each run's traces are grouped in Langfuse under
the session `<eval-run-id>` and tagged `model:…`, `scenario:…`, `eval-run:…`.
