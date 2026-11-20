# 04: Fixture world and evals use the e-mail transport

**Type:** task

**What to build:** `fixture_world.informer` builds the e-mail transport against the MS365 stand-in (`python -m fixture_world.ms365`, the same arguments as the real server), with made-up addresses, in place of `RecordingHandover`. Remove `RecordingHandover`, its log variables (`FIXTURE_WORLD_PURCHASE_UPLOAD_LOG`, `FIXTURE_WORLD_PURCHASE_HANDOVER_FAIL`) and `read_upload_log`. The eval upload outcome grade reads the stand-in's sent log and requires the configured sender and recipient. The upload-failure scenario uses the stand-in's send failure switch. The environment allowlist forwards only the `FIXTURE_WORLD_*` variables the stand-in needs.

**Blocked by:** 03

**Status:** ready-for-agent

- [ ] In fixtures mode (`python -m agent.cli --fixtures`), an approved upload is recorded by the stand-in as one sent message with the right file
- [ ] The upload outcome grade fails a run whose message went to another recipient or came from another sender
- [ ] The approve, reject, failure-reported and mixed-step upload scenarios keep their meaning: one message after approve, none after reject, the failure reported in the answer
- [ ] No reference to `RecordingHandover` or the old upload log variables remains
- [ ] The full suite passes (`uv run pytest -m "not live and not browser"`)

Spec: `../spec.md` (Fixture world and evals). ADR-019.

## Comments
