# 07: Prompt v7: Process, "Process instead?", and the status line

**Type:** task

**What to build:** `PROMPT_V7` in `src/agent/prompts.py`, written out in full (a single literal), `v6` plus these rules, registered and made the default (`config.py`):
- before Uploading a Purchase invoice, read the invoice date with `read_pdf_text`; ask the owner when there is none;
- before an Upload to OneDrive, run the Processed check and pass its target path unchanged;
- when the owner asks for only one upload and the other is missing (`informer_check_purchase_invoice` reports no earlier upload, or the Processed check says not Processed), ask "Process instead?" first; when the other is already done, just do what was asked;
- to Process, propose `informer_upload_purchase_invoice` and `ms365_upload_to_onedrive` together in one turn; if one fails, report it and offer the remaining step;
- every answer about a Purchase invoice ends with `Uploaded to Informer: yes (<date>)/no · Uploaded to OneDrive: yes (<path>)/no`; without a file, the OneDrive status comes from the listing and says it matched names only.

Released versions are not edited: `RELEASED` in `tests/test_released_prompt_versions.py` gains `v7`'s sha256, and the prompt tests that count versions or name the default are updated.

**Blocked by:** 04, 05, 06

**Status:** resolved

- [x] `v7` starts with `v6` and adds only the rules above (a test, as for `v6`)
- [x] `v7` is the default and is in `RELEASED`; no earlier version's hash changes
- [x] A scripted-model graph test: two Write actions in one turn give one Approval listing both, and both run
- [x] The full suite passes (`uv run pytest -m "not live and not browser"`)

Spec: `../spec.md` (Prompt; Process). ADR-020.

## Comments

- 2026-11-24: Built. `PROMPT_V7` in `src/agent/prompts.py` is `v6` plus a "Purchase invoices:" section (the glossary terms mapped to the tools; invoice date from `read_pdf_text`, else ask; the Processed check before an Upload to OneDrive, Target path unchanged; "Process instead?" when the other upload is missing; a Process is both uploads in one turn, a failure offers the remaining step; the status line, with the listing's OneDrive status said to match names only). Default in `config.py`; `RELEASED` gains its sha256. Tests: `tests/test_agent_prompts.py` (v7 default, 7 versions, v7 starts with v6 and adds the rules), `tests/test_process_purchase_invoice.py` (scripted model over `load_all_tools(fixtures=True)`: one Approval listing both uploads, both run: one sent message, one archived file). Full suite green.
