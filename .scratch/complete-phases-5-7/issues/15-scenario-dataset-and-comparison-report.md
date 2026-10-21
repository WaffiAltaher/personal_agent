# 15: Full scenario dataset + model-comparison report

**What to build:**
- A versioned dataset of 10–20 scenarios over the Fixture world, covering:
  - inbox triage
  - the overdue-invoice capstone
  - finance questions
  - research
  - failure recovery
  - rejection
- A repeats option.
- A report generator that compares two models across quality, trajectory, cost and latency, with variation across repeats.

The real Gemini vs Claude run is ticket 18.

**Blocked by:** 12, 14

**Status:** resolved

- [x] 10–20 scenarios, each runnable against the Fixture world
- [x] The repeats option produces per-scenario variation in the results
- [x] The comparison report is generated from two results files
- [x] Tested end to end with scripted models

## Comments

- Dataset `src/agent/evals/datasets/scenarios.json` (version `2026-10-07.2`): 18 scenarios. Inbox triage 5, capstone 2, finance 4, research 2, failure recovery 3 (MS365 transient once, Informer 401, MS365 logged out), rejection 2. `tests/test_eval_dataset.py` runs every scenario end to end with a scripted model (calls its required tools, then answers) and checks that every expected fact appears in those tool outputs, so the facts can be derived from the seeded Fixture world.
- `--repeats N` (`run_eval(repeats=N)`, `EvalResults.repeats`); report rows are labelled `<scenario> #k` when N > 1.
- `python -m agent.evals compare a.json b.json [--out DIR]` → `compare-<runA>-vs-<runB>.md` (`src/agent/evals/compare.py`): summary (trajectory, facts, RAGAS, tokens, cost, latency) and one row per scenario and model, showing mean (min–max) across repeats. It warns when the dataset or prompt versions differ, when a model graded its own answers, or when the judges differ.
- Fixed gap (a): `build_graph(today=...)` pins the date in the model's runtime context to 09:00 Europe/Amsterdam. Evals pass the seeded date. `--fixtures` calls `fixture_world.clock.pin_today()`, which uses FIXTURE_WORLD_TODAY or else SEED_TODAY, sets the env for the stand-ins, and tells the model the same date. INFORMER_TODAY plays no part in fixture mode (the fixture launcher derives it from the clock).
- Fixed gap (b): in Fixture-world mode, `load_all_tools(fixtures=True)` binds `fixture_web_search` instead of Tavily. It has the same tool name (`tavily_search`) and argument schema, is classified read, and serves seeded pages from `fixture_world/data/web/search_results.json` (`.example` domains). Before this, evals bound no web search at all: `EVAL_LOCAL_TOOLS` named `web_search`, but the bound tool is called `tavily_search`.
- The commands for the real run are in ticket 18's "Owner follow-up".
