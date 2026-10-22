# 23: Comparison statistics and judge labels

**Type:** task

**Model:** Composer 2.5

**Blocked by:** None (can start immediately)

**Status:** resolved

**Closes:** F10, F11, F12, F13

**What to build:** Model comparison reports show the paired difference in pass rate with a 95% range clustered by scenario, a plain "can't tell these apart with this many runs" verdict when the range includes zero, and pass^k (the share of scenarios that passed every repeat). Judge-based quality scores are labelled "unvalidated LLM judge". A warning appears when the judge and a compared model share a provider, not only when they're the same model. Answer-quality averages show how many runs were scored and are never computed over a silently shrunk set.

- [x] Test: two result sets with a small difference produce the "can't tell apart" verdict; a large difference doesn't
- [x] Test: the range is computed over scenarios (paired), not over individual runs
- [x] Test: pass^k counts a scenario only when all its repeats passed
- [x] Test: same-provider judge warns; different-provider doesn't
- [x] Test: when some runs couldn't be scored, the report says how many were scored

Spec: `../spec.md`. Decisions: `../findings.md` ("Decisions taken").

## Comments

Implemented in `compare.py` with tests in `test_eval_compare_stats.py`; paired stats use Exp 8 formula (mean ± 1.96×SE over scenario diffs).
