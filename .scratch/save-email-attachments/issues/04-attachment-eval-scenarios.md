# 04: Eval scenarios for saving attachments, including Outlook to Informer

**What to build:** The eval suite measures the feature's actual purpose. One scenario saves a Gmail attachment and is approved. One saves an Outlook attachment and is rejected. One takes a Purchase invoice from an Outlook email, saves it, and uploads it to Informer, with both steps approved. Each is graded on what's on disk and what the fake Informer recorded, not just on which tools were called.

**Blocked by:** 02, 03

**Status:** ready-for-agent

- [ ] The eval harness points the agent folder at the run's working directory, as it already does for the eval Downloads folder
- [ ] Outcome grading can check files in the agent folder: their presence, location (`gmail/` or `outlook/`) and exact bytes, next to the existing upload log
- [ ] Scenario: save the Gmail attachment, approved. The file is in `gmail/` with the seeded bytes.
- [ ] Scenario: save the Outlook attachment, rejected. Nothing is written anywhere in the agent folder.
- [ ] Scenario: Outlook email → save → Informer upload, both approved. The file is in `outlook/`, and the fake Informer recorded exactly one upload, with that file's bytes. The run gets two Approvals.
- [ ] The Informer upload in the chain scenario accepts the saved path. The eval's Informer Downloads folder must contain the agent folder; adjust the harness if it doesn't.
- [ ] A unit test covers the new outcome scoring (prior art: the upload-outcome scenario tests)
- [ ] The dataset validation tests pass with the new scenarios
- [ ] The whole suite passes

Traps:
- The prompt names the real `~/Downloads/personal_agent`, but in evals the files go to a temporary folder. Grade on the paths the tools actually returned or wrote, not the prompt's path.
- An inline logo saved by mistake is a failure of the Gmail and Outlook scenarios, not noise.

Spec: `../spec.md` (Evals).
