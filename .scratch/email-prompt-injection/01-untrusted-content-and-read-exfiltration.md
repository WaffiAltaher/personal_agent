# 01: Prompt injection through email and file contents

**Status:** needs-triage

**What to build:** To be decided. This ticket records a risk found while designing attachment saves (2026-10-25). It doesn't settle a fix.

Email bodies, attachments listed by name, files and web results reach the model as tool results. Models tend to treat those as data, not instructions, but a well-written injection can still steer the model.

What already protects the owner:
- Every Write action stops for Approval.
- Nothing can send mail.

What doesn't:
- **Reads run without Approval.** An injected instruction could make the agent search other mail and put what it found into a `web_search` query. That sends data to an outside service (Tavily) without the owner seeing it.
- **No prompt version says** that tool-result content is untrusted.
- **The final answer can be steered,** e.g. an email claiming an invoice is already paid.

Questions to settle:
- Should `web_search` (or any read that sends arguments outside) be treated differently?
- Is a prompt rule worth adding, given that it can't be relied on?
- Which evals would show the risk with a seeded injection email in the Fixture world?
