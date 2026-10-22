# 28: Land the remaining killing tests

**Type:** task

**Model:** Haiku

**Blocked by:** 09, 13

**Status:** resolved

**Closes:** Track B mutants M5, M6, M19, M20, M39, M41, M42 (k05, k06, k19, k20, k39, k41, k42)

**What to build:** Add the remaining verified Track B killing tests to the suite: `k05_http_status_boundaries`, `k06_backoff_grows`, `k19_flush_before_exit`, `k20_resume_is_traced`, `k39_unknown_prompt_version_is_refused`, `k41_eval_traces_name_the_prompt_that_ran`, `k42_cli_traces_record_the_prompt_version`. Each was verified to pass on the real code and fail on its mutant; after tickets 09 and 13 some may need adjusting to the new entry point or prompt default, without weakening what they assert.

- [x] All seven tests are in the suite and pass
- [x] Any test that needed adapting still fails on its mutant (check by hand against the Track B mutants list; don't commit mutants)
- [x] k41 still uses a non-default prompt version

Spec: `../spec.md`. Decisions: `../findings.md` ("Decisions taken").

## Comments

- Added the seven notebook tests as `tests/test_k05…`, `test_k06…`, `test_k19…`, `test_k20…`, `test_k39…`, `test_k41…`, `test_k42…`, unchanged: none needed adapting after tickets 09 and 13. k41 still uses `v2`, not the default `v4`. Each fails on its mutant (M5, M6, M19, M39, M41, M42, and an equivalent of M20 on the `run_conversation` resume, because M20's text was replaced by ticket 09). Checked in a throwaway copy, nothing committed. Full suite: 322 passed (live tests excluded).
