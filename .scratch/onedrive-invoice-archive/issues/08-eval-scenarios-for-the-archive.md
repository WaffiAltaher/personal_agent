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

**Status:** resolved

- [x] Each scenario passes with a scripted model that does the right thing, and the outcome grade fails a scripted run that files the wrong month, writes an extra file, or uploads only one half of a Process
- [x] The existing upload and attachment scenarios keep their meaning
- [x] No test makes a live model call
- [x] The full suite passes (`uv run pytest -m "not live and not browser"`)

Spec: `../spec.md` (Fixture world and evals; Testing Decisions). ADR-020.

## Comments

- 2026-11-24: Built. Harness: each run gets its own drive (`<workdir>/drive`, seeded from `data/ms365/drive/` on first use; the seeded paths are snapshotted and don't count), `FIXTURE_WORLD_MS365_DRIVE_FAILURE` cleared unless `inject_failure.server == "drive"` (`transient` only, no `times`), the Informer upload log seeded from the new `Scenario.informer_uploads` (Downloads file name -> date, written with the Informer server's `fingerprint`), and `settings.informer_downloads_dir` pointed at the run's Downloads beside `settings.agent_folder`. `ExpectedOutcome.archived_files` is a dict, drive path -> eval Downloads file whose bytes it must hold (so a renamed path can name its source); `score_outcome(archived=, expected_archive=)` grades it like `saved_files`; `OutcomeScore.archived_files` lists what the run added. "invoice archive" scenarios are told the Downloads path, like "upload" ones. Nine scenarios, dataset `2026-11-24`. Eval Downloads gain `hosting-2026-10.pdf` (new, dated 05-10-2026, before the Fixture world's today 2026-10-07), `kpn-oktober.pdf` (the seeded `kpn-factuur-123456.pdf`'s bytes: same contents, other name, for `processed-check-by-file`) and `Factuur.pdf` (the seeded September file's bytes: same name and contents). The ticket-06 `kpn-factuur-123456.pdf` is kept as is and used deliberately as the different-contents name clash (renamed to `kpn-factuur-123456 1.pdf`); its printed date 14-10-2026 is after the Fixture world's today, which a live model may remark on (ticket 06's tests pin it). The Approval's target path is not a separate grade: the upload refuses any target but the renamed one, so the archived renamed file implies the Approval showed it (a test also checks the actions text). `process-drive-failure` fails the drive for the whole run, so the Processed check fails too; the grade asks for the Informer upload, nothing archived and "503"/"unavailable" in the answer. Tests: `tests/test_eval_invoice_archive_scenarios.py` (grade units; every scenario passes its right script; wrong month, extra file and either half alone fail; the graded facts come from the seeded world's tool outputs; per-run drive; drive switch cleared), `tests/test_eval_dataset.py` updated. No live model calls; the scenarios have not been run against a real model yet (owner's call).
