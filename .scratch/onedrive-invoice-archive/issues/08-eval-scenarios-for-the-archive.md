# 08: Eval scenarios for Process, single uploads, the Processed check and name clashes

**Type:** task

**What to build:** The harness gives each run its own drive directory seeded from `src/fixture_world/data/ms365/drive/` (`FIXTURE_WORLD_MS365_DRIVE`), clears `FIXTURE_WORLD_MS365_DRIVE_FAILURE` unless the scenario fails the drive, and can seed the Informer upload log. `FailureInjection` gains a `drive` server (mode `transient` only). `ExpectedOutcome` gains `archived_files` (archive paths, each compared with the expected bytes), and `score_outcome` grades it from the stand-in's archive, like `saved_files`; files that were seeded don't count. New scenarios in `datasets/scenarios.json` (the dataset version bumped):
- `process-approved`: one sent message and one archived file in the invoice date's month, one Approval;
- `onedrive-only-asks-process`: Informer not done, asks "Process instead?", nothing uploaded;
- `onedrive-only-informer-done`: seeded Informer upload log, no question, one archived file;
- `processed-check-by-file` and `processed-list-by-month` (the answer says names only);
- `onedrive-name-clash-same-contents` (no-op, reported) and `onedrive-name-clash-different-contents` (renamed, and the Approval's target path shows the renamed path);
- `onedrive-scanned-pdf-asks-date`: nothing uploaded, asks for the date;
- `process-drive-failure`: the Informer upload sent, the OneDrive failure reported, the remaining step offered.

**Blocked by:** 07

**Status:** ready-for-agent

- [ ] Each scenario passes with a scripted model that does the right thing, and the outcome grade fails a scripted run that files the wrong month, writes an extra file, or uploads only one half of a Process
- [ ] The existing upload and attachment scenarios keep their meaning
- [ ] No test makes a live model call
- [ ] The full suite passes (`uv run pytest -m "not live and not browser"`)

Spec: `../spec.md` (Fixture world and evals; Testing Decisions). ADR-020.

## Comments
