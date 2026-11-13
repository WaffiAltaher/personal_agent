# 17: Refuse duplicate uploads unless asked

**Type:** task

**Model:** Haiku

**Blocked by:** 16

**Status:** resolved

**Closes:** (decision on duplicate uploads, as amended by Q37)

**What to build:** The Informer server keeps an upload log (path in its settings) with a fingerprint of each successfully handed-over file's contents and the date. `check_purchase_invoice` reports "already uploaded on <date>" when the contents (under any name) are in the log. `upload_purchase_invoice` gains `allow_duplicate` (default false): a repeat of logged contents is refused with the earlier date unless it is true, so a deliberate re-upload shows as `allow_duplicate: true` in the Approval's raw arguments. The tools' descriptions tell the model to ask the owner before re-uploading.

- [x] Test: after one upload, checking the same contents under another name reports the first upload's date
- [x] Test: uploading the same contents again without `allow_duplicate` is refused with that date and hands nothing over
- [x] Test: with `allow_duplicate` true it hands the file over
- [x] Test: a refused or failed upload isn't logged as uploaded
- [x] Test: different contents are neither reported nor refused

Spec: `../spec.md`. Decisions: `../findings.md` ("Decisions taken").

## Comments

- Implemented on `ticket/17-duplicate-upload`: upload log is a file (`purchase_upload_log` setting, default `~/.informer_mcp/purchase-uploads.jsonl`) of SHA-256 fingerprint and date per successful hand-over; `check_purchase_invoice` reports `already_uploaded_on`/`warning`; `upload_purchase_invoice(path, allow_duplicate=false)` refuses repeats with the earlier date and logs only after a successful hand-over; over-cap files are refused by `stat` before `read_bytes`. Fixture world takes its log and downloads folder from `FIXTURE_WORLD_INFORMER_UPLOAD_LOG` and `FIXTURE_WORLD_INFORMER_DOWNLOADS_DIR`, since the child env allowlist (ticket 11) forwards only `FIXTURE_WORLD_*`.
- Tests: 31 pass in `tests/informer_server/test_purchase_upload.py` and `tests/test_fixture_world_informer_uploads.py`; full suite 294 passed, 1 deselected (live).
