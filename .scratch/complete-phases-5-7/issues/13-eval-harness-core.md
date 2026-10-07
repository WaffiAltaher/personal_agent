# 13: Eval harness core + trajectory metrics

**What to build:** The learner runs one command to evaluate the agent on scenarios over the Fixture world, with a chosen model. Each scenario declares:
- the input
- the approval policy (auto-approve or auto-reject)
- any failure to inject
- the required tools and ordering constraints
- the forbidden tools
- the expected answer facts

The harness scores trajectory metrics: tool-selection precision and recall, whether ordering constraints were met, forbidden-tool violations, and recovery after an injected failure. It writes results JSON and a markdown report.

**Blocked by:** 06, 11

**Status:** ready-for-agent

- [x] Versioned scenario format and loader
- [x] Runner injects the model and applies the approval policy and failure injection
- [x] Trajectory metrics computed per scenario and aggregated
- [x] Tested with a scripted fake model on 2 scenarios (one pass, one deliberate trajectory failure)

## Comments

- Implemented in `src/agent/evals/`: `scenarios.py` (format v1 + loader; pydantic, unknown keys rejected), `harness.py` (`run_scenario` / `run_eval` / `write_results`), `trajectory.py` (scores + summary), `records.py` (result records), `report.py` (markdown), `__main__.py`. Run: `uv run python -m agent.evals --model <provider:model> [--scenario <id substring>] [--dataset <file>] [--out data/evals]`. Starter dataset (3 scenarios) in `src/agent/evals/datasets/scenarios.json`; ticket 15 expands it. Tests: `tests/test_eval_harness.py` with `tests/fixtures/evals/scenarios.json`.
- Each scenario run gets a fresh Fixture world (clock pinned to `SEED_TODAY`, its own Drafts file and MS365 failure switch). An MS365 failure is switched on after the tools load, so it hits the run, not startup; an Informer failure is the env mode on every request.
- Evals bind only the Fixture world's MCP tools plus `EVAL_LOCAL_TOOLS` (`web_search`): the Gmail, Calendar, memory and file tools reach real data, and auto-approve would make a Gmail draft real.
- Scoring: precision/recall over distinct tool names; an ordering constraint holds when `before` was first called in an earlier model turn than `after`; recovered = a run with an injected failure still completed with a final answer; passed = completed, recall 1.0, ordering met, no forbidden tool, recovered. Expected facts are scored by case-insensitive substring (`answer_facts`) but are not part of `passed`.
- For ticket 14: tool outputs are kept per call in `RunResult.tool_calls[*].output` (the RAGAS contexts); add tokens/cost/latency and generation scores as defaulted fields on `RunResult` / `Summary`; `prompt_version` is already in `EvalResults`. For 15: `RunResult.repeat` exists, `run_eval` runs each scenario once.
- Known gap: the model's runtime context carries the real date, while the Fixture world is pinned to 2026-10-07.
