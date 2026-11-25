# 06: A save with the attachment's ID as message ID is refused before the owner is asked

**Type:** task

**What to build:** On 2026-11-25 (thread `d69a733e…`, processing the Centraal Beheer nota) the agent proposed `ms365_save_attachment` with the PDF's attachment ID in both `message_id` and `attachment_id`. The owner approved, Graph answered `400 ErrorInvalidAttachmentId`, and the corrected call needed a second Approval. An Outlook attachment ID starts with almost all of its message's ID, so the raw IDs in the Approval give the owner no chance to spot it.

A Write action can carry a pure pre-approval check of its arguments (`with_pre_approval_check` in `classification.py`). `human_review_node` runs it on every call that needs Approval; a refused call is answered with the check's error ("Nothing was run and the owner was not asked…") and left out of the Approval, and the model corrects it on its own. A refused call never runs, so nothing skips an Approval it needed. `ms365_save_attachment` refuses `message_id == attachment_id`. The owner chose only this check (not a description change, not deriving the message ID from the attachment ID).

**Blocked by:** None

**Status:** resolved

- [x] A failing check answers the call with an error and no interrupt; the tool never runs
- [x] A passing check still asks the owner
- [x] In a batch, only the calls that pass are put to the owner; the refused one's error is kept after approve and reject
- [x] `ms365_save_attachment` refuses equal IDs and allows different ones, also as bound by `load_all_tools`

Spec: `../spec.md`. ADR-010 (fails closed: the check can only refuse a call, never let one skip Approval).

## Comments

- Tests: `tests/test_pre_approval_check.py` (4, red first: the import failed), and one in `tests/test_save_outlook_attachment.py` (the bound tool keeps its check; passed first time, as a guard against the loader dropping metadata).
