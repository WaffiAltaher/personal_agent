# 17: Refuse duplicate uploads unless asked

**Type:** task

**Model:** Haiku

**Blocked by:** 16

**Status:** ready-for-agent

**Closes:** (decision on duplicate uploads, as amended by Q37)

**What to build:** The Informer server keeps an upload log (path in its settings) with a fingerprint of each successfully handed-over file's contents and the date. `check_purchase_invoice` reports "already uploaded on <date>" when the contents (under any name) are in the log. `upload_purchase_invoice` gains `allow_duplicate` (default false): a repeat of logged contents is refused with the earlier date unless it is true, so a deliberate re-upload shows as `allow_duplicate: true` in the Approval's raw arguments. The tools' descriptions tell the model to ask the owner before re-uploading.

- [ ] Test: after one upload, checking the same contents under another name reports the first upload's date
- [ ] Test: uploading the same contents again without `allow_duplicate` is refused with that date and hands nothing over
- [ ] Test: with `allow_duplicate` true it hands the file over
- [ ] Test: a refused or failed upload isn't logged as uploaded
- [ ] Test: different contents are neither reported nor refused

Spec: `../spec.md`. Decisions: `../findings.md` ("Decisions taken").
