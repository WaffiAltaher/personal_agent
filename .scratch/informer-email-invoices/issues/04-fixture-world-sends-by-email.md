# 04: Fixture world and evals use the e-mail transport

**Type:** task

**What to build:** `fixture_world.informer` builds the e-mail transport against the MS365 stand-in (`python -m fixture_world.ms365`, the same arguments as the real server), with made-up addresses, in place of `RecordingHandover`. Remove `RecordingHandover`, its log variables (`FIXTURE_WORLD_PURCHASE_UPLOAD_LOG`, `FIXTURE_WORLD_PURCHASE_HANDOVER_FAIL`) and `read_upload_log`. The eval upload outcome grade reads the stand-in's sent log and requires the configured sender and recipient. The upload-failure scenario uses the stand-in's send failure switch. The environment allowlist forwards only the `FIXTURE_WORLD_*` variables the stand-in needs.

**Blocked by:** 03

**Status:** resolved

- [x] In fixtures mode (`python -m agent.cli --fixtures`), an approved upload is recorded by the stand-in as one sent message with the right file
- [x] The upload outcome grade fails a run whose message went to another recipient or came from another sender
- [x] The approve, reject, failure-reported and mixed-step upload scenarios keep their meaning: one message after approve, none after reject, the failure reported in the answer
- [x] No reference to `RecordingHandover` or the old upload log variables remains
- [x] The full suite passes (`uv run pytest -m "not live and not browser"`)

Spec: `../spec.md` (Fixture world and evals). ADR-019.

## Comments

- 2026-11-20 (claude): `fixture_world.informer` now builds `EmailHandover` against the MS365 stand-in (`ms365_stand_in_parameters()`: `python -m fixture_world.ms365` with the real server's arguments, now shared as `email_handover.SERVER_ARGS`, a temp-dir cwd, and of the `FIXTURE_WORLD_*` variables only the clock, sent log and failure switches), from the made-up `INVOICE_MAILBOX` to `INCOMING_ADDRESS`. Removed `src/fixture_world/purchase_handover.py` (`RecordingHandover`, `FIXTURE_WORLD_PURCHASE_UPLOAD_LOG`, `FIXTURE_WORLD_PURCHASE_HANDOVER_FAIL`) and `read_upload_log`. `score_outcome` takes the stand-in's sent messages and fails any not from the Invoice mailbox to the incoming address only; the harness gives each run its own `FIXTURE_WORLD_MS365_SENT` and maps a `handover` failure (now mode `transient` only) to `FIXTURE_WORLD_MS365_SEND_FAILURE`; `upload-handover-failure` expects "503"/"unavailable" in the answer. `RunResult.upload_log_path` keeps its name (older result files still load) and now points at the sent log. New tests: two in `tests/test_fixture_world_informer_uploads.py` (an upload over `--fixtures` is one sent message with the file; the stand-in's environment), two in `tests/test_eval_outcome_upload_scenarios.py` (sender/recipient grade; failure scenario sends nothing and passes when reported); `sent_upload` helper in `tests/conftest.py`. Suite: 723 passed, 6 deselected.
