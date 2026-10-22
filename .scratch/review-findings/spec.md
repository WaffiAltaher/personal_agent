# Spec: Review findings — fix the agent, refocus Informer, make runs safe and cheap

Status: ready-for-agent

Source: the findings register in this folder (`findings.md`), whose "Decisions taken (grilling, 2026-10-22)" section is the authority for every decision below; finding IDs (B1, E6, k10, …) refer to it. Vocabulary follows `GLOSSARY.md` (Approval, Write action, Purchase invoice, Revenue, VAT to pay, Sales invoice, Client, Relation, Draft, Fixture world); agent-engineering terms follow `learning/GLOSSARY.md`. Decisions respect `docs/ARCHITECTURE_DECISIONS.md`, especially ADR-010 (as amended 2026-10-22), ADR-011 (amended), ADR-012, ADR-013 and ADR-014.

Implementers will be cheaper models running unattended. Every ticket names its traps and its tests; when a ticket and this spec disagree, stop and report rather than guess.

## Problem Statement

The owner runs the agent every day over ITtopia's Outlook mailbox, Informer accounting, and their personal Gmail and Google Calendar. A review (Track B notebooks 01–11 and live runs) found that it is unsafe in places, breaks on ordinary outages, measures the wrong things, and was built around a use of Informer the owner doesn't have.

- **It breaks on ordinary outages.** When the local Langfuse isn't running, every CLI run crashes before the agent starts, looking like a broken tool connection. When the Google login has expired, every Gmail and Calendar tool fails with a raw error, and the only fix is to know to delete a token file by hand.
- **Approval can fail open and can lie.** Any answer except the exact word "reject" approves a Write action. Rejecting a batch tells the model the owner rejected the reads too, which the owner never saw. A new message sent while an Approval is pending silently drops it and leaves a tool call unanswered, so the next model call fails. Resuming with no decision crashes; resuming an unknown conversation silently starts an empty run.
- **Runs aren't bounded.** The step limit resets after every Approval, so a run that keeps asking for approvals never stops.
- **Context handling destroys the conversation.** Above the hard limit the agent deletes the owner's question first, can leave a tool result without its call, and one oversized tool result deletes every message, permanently. It counts tokens wrongly (missing tool-call arguments, the system prompt and the tool definitions), and its limits are sized to one model's window rather than to quality or cost.
- **Memory is a liability.** Every answer, right or wrong, is stored and later retrieved as trusted context: a feedback loop and a stored prompt-injection path. The similarity threshold doesn't mean what it says. Searching past runs only finds exact substrings, so natural questions ("what did I ask about VAT last week?") find nothing, and a hidden rewrite call fails silently.
- **Informer does the wrong job.** The Phases 5–7 build added overdue-invoice detection and Payment reminder Drafts. The owner uses Informer for exactly two things: questions about the financial situation (Revenue, VAT to pay, …), and handing over a Purchase invoice as just a file for the accountant to book. The agent can do neither well: it adds up ledgers by itself in the prompt and has no way to upload a file.
- **Real personal data leaks into tests and evals.** Fixture-world mode still binds the real Gmail and Calendar tools, so evals can read the owner's real inbox.
- **Third-party code sees everything.** The MCP servers inherit the owner's whole environment, including every API key, and the Microsoft 365 server reads the repo's `.env` on its own.
- **Every model call pays full price for the same opening.** The system prompt changes on every call (it carries the current time), tools aren't in a fixed order, and Claude models aren't asked to cache.
- **Evals can't support decisions.** Nothing grades outcomes, only paths and words. "Recovered" means "didn't crash". A comparison of two models shows two pass rates with no sense of whether the gap is noise. The LLM judge has never been checked.
- **The tests miss real bugs.** Track B mutation testing found many changes that would let user-visible bugs through with every test passing; killing tests for them are written and verified but not in the suite.

## Solution

After this work:

- The CLI starts and answers even when Langfuse is down, with a warning naming the Langfuse address. When the real Google tools are in use and the Google login is missing or dead, startup stops with a message naming the one command that logs in again; a browser never opens in the middle of a run.
- An Approval covers exactly the Write actions the agent proposed together. Only "approve" approves; anything else rejects. When the owner rejects, the reads proposed alongside still run, and the model is told only the Write actions were rejected, as errors. If the owner sends a new message instead of answering, the pending Write actions count as rejected and the new message is handled normally. Bad resumes are refused with a clear error.
- A run stops after a fixed number of model calls, counted across Approvals, with an answer saying it hit the step limit.
- Context never loses the conversation. When it gets large, old tool results are hidden from the model (with a note saying they can be fetched again) while every message is kept. A single huge tool result is cut down where it is returned, with a marker. The limits are sized for quality and cost, and the count is accurate.
- Memory holds only what the owner explicitly asked it to remember, each memory approved like any Write action. Past runs are searched by words and dates the agent chooses itself, ranked by relevance, and the agent tries again when a search finds nothing.
- Informer answers Revenue and VAT-to-pay questions with exact amounts computed in code, still answers other financial questions from the trial balance, and hands a Purchase invoice PDF from the Downloads folder to Informer (checked first for type, size and earlier uploads) for the accountant to book; the real hand-over route is a follow-up, so until it exists only the Fixture world offers uploads. Overdue invoices and Payment reminders are gone.
- Fixture-world mode never touches real Google, Microsoft 365 or Informer data.
- MCP servers see only the environment variables they need.
- Within a run, every model call starts with the identical tools-plus-system-prompt opening, Claude models are asked to cache it, and cached tokens are recorded in usage and cost.
- Evals grade what matters for the two Informer uses (exact amounts, the upload outcome, a mixed batch), comparisons say when a difference is too small to trust, and judge scores are labelled as unvalidated.
- Every Track B killing test that still applies is in the suite.

## User Stories

### Reliability at startup and on failure

1. As the owner, I want the CLI to answer my question even when Langfuse isn't running, so that a tracing outage never blocks my work.
2. As the owner, I want the warning about Langfuse to name the address it tried, so that I know which service to start.
3. As the owner, I want a dead or missing Google login to stop startup with the exact command to log in again, so that I never have to know which token file to delete.
4. As the owner, I want a dead Google token to be removed automatically when it is detected, so that the re-login command starts clean.
5. As the owner, I want a command that logs me in to Google and saves the token, so that recovering takes one line.
6. As the owner, I want a browser never to open in the middle of a run, so that a run is never left waiting on a window I didn't expect.
7. As the owner, I want the Google login check to run only when the real Google tools are in use, so that tests, evals and `--fixtures` never need a Google login.
8. As the owner, I want the Google login explanation to state that Testing-mode tokens expire seven days after issue, so that the docs match what happens.
9. As the owner, I want two tool failures in the same step to be recorded rather than crash the run, so that one bad batch doesn't kill the conversation.
10. As the owner, I want the fallback for an unexpected tool crash to mark its message as an error and describe the actual failure, so that the model doesn't think a crash was a success or a temporary outage.
11. As the owner, I want transient failures (connection errors, timeouts, HTTP 429 and 5xx, Informer's per-minute 429, Microsoft Graph's throttling 429) to be retried with growing waits, and permanent ones not, so that brief outages heal themselves and real errors surface at once.
12. As the owner, I want the CLI to flush traces before it exits and to trace the part of a run after an Approval, so that a run's trace is complete.
13. As the owner, I want the CLI to handle a second and later Approval in the same run, so that no proposed Write action is silently skipped.

### Approval

14. As the owner, I want only an explicit "approve" to approve, and anything else to reject, so that a typo never sends something on my behalf.
15. As the owner, I want one Approval to cover all the Write actions proposed together, so that I answer once per step.
16. As the owner, I want reads proposed alongside a rejected Write action to still run, so that rejecting an upload doesn't also cancel the question I asked.
17. As the owner, I want rejected Write actions reported to the model as errors and as rejected by me, so that it neither claims success nor blames me for reads I never saw.
18. As the owner, I want a rejected Write action to be impossible to execute, so that rejecting is always safe.
19. As the owner, I want sending a new message instead of answering an Approval to count as rejecting it, so that I can change my mind by just asking something else.
20. As the owner, I want a resume with no decision, or with a decision for a conversation that has no pending Approval, to be refused with a clear error, so that a future frontend can't silently start an empty run or crash.
21. As the owner, I want every Approval to show what each Write action will do in plain terms, so that I approve with understanding rather than reading raw arguments.

### Run limits

22. As the owner, I want each run limited to a set number of model calls, so that a looping model can't run up a bill.
23. As the owner, I want that count to carry across Approvals within the run and to start again with my next message, so that approving doesn't reset the limit and a new question gets a fresh budget.
24. As the owner, I want a run that hits the limit to end with an answer saying so, so that I know why it stopped.
25. As the owner, I want evals to use the same limit and to record a run that hits it as a step-limit result, so that eval costs are bounded the same way.

### Context

26. As the owner, I want my question to stay visible to the model however long the run gets, so that the agent never answers without knowing what I asked.
27. As the owner, I want old tool results hidden from the model only when the context is large, with a note saying how big they were and that they can be fetched again, so that big results don't crowd out reasoning.
28. As the owner, I want nothing deleted from the saved conversation when context is reduced, so that the reduction is reversible and the history always stays valid.
29. As the owner, I want a single huge tool result cut down to a fixed size with a marker saying it was truncated, so that one large response can't fill the context.
30. As the owner, I want the size of the context counted accurately, including the system prompt, the tool definitions and tool-call arguments, so that reductions happen when they should.
31. As the owner, I want a reduction to bring the context well below the threshold, so that it doesn't fire again on the very next step.
32. As the owner, I want retrieved memory to have a fixed budget, so that memories never crowd out the conversation.

### Memory

33. As the owner, I want the agent to store a memory only when I ask it to remember something, and only after I approve it, so that wrong answers and injected text never become trusted memory.
34. As the owner, I want my answers no longer copied into long-term memory or sent to the embeddings service, so that less of my data leaves my machine.
35. As the owner, I want a memory search that finds nothing relevant to return nothing, so that unrelated memories don't pollute an answer.
36. As the owner, I want the relevance threshold to mean real similarity and to be chosen from labelled examples, so that "relevant" is a measured claim.
37. As the owner, I want to ask what I asked about a topic in a given period and get the matching past runs, so that I can find earlier work naturally.
38. As the owner, I want the agent to retry a search of past runs with other words when the first search finds nothing, so that one bad guess doesn't end the search.
39. As the owner, I want the run log to record each run's total usage, cost and real outcome (completed, step limit, error, rejected), so that my history is accurate.
40. As the owner, I want problems writing the run log to be logged, not swallowed, so that I notice when history stops being recorded.

### Informer: financial questions

41. As the owner, I want to ask for Revenue over any range of periods in a year and get the exact amount, so that I can trust the number.
42. As the owner, I want to ask how much VAT I have to pay for a quarter and get the exact amount, including when it is negative (owed back to me), so that I can prepare the VAT return.
43. As the owner, I want other financial questions answered from the trial balance, so that I'm not limited to two questions.
44. As the owner, I want amounts quoted exactly as computed, never rounded or recomputed by the model, so that numbers match Informer.

### Informer: Purchase invoice upload

45. As the owner, I want to upload a Purchase invoice by giving the path of a PDF file, so that my accountant can book it.
46. As the owner, I want the upload to send only the file, with no invoice details, so that my accountant applies the bookkeeping themselves.
47. As the owner, I want every upload to need my Approval and never be retried automatically, so that nothing reaches my books without me and nothing is uploaded twice by a retry.
48. As the owner, I want only PDF files under a size cap, whose content really is PDF, from my Downloads folder or any folder inside it, to be accepted, so that the agent can never upload a key, a contract or a file from elsewhere.
49. As the owner, I want the agent to check a file before proposing its upload and tell me its name, size and any earlier upload, so that I know exactly what is being sent.
50. As the owner, I want a repeat of contents uploaded before to be refused, with the earlier date, unless the agent explicitly asks to upload it again (visible in the Approval as `allow_duplicate: true`), so that I don't create duplicate records by accident but can re-upload on purpose.
51. As the owner, I want the upload tools hidden until a real way of handing the file to Informer exists, so that the agent never offers something it can't do.
52. As the owner, I want a failed upload reported plainly in the answer, so that I know it didn't go through.
53. As the owner, I want a small probe script I can run once against Informer's v1 upload, so that we learn what a file-only upload really produces before building on it.

### Informer: removing the wrong work

54. As the owner, I want overdue-invoice detection, the Payment reminder prompt and their rules removed, so that the agent doesn't offer a workflow I don't use.
55. As the owner, I want the Informer server's description to say it reads accounting data and, when the upload tools are present, accepts Purchase invoice uploads, so that the model knows what it can do there.

### Fixture world and MCP servers

56. As the owner, I want seeded stand-ins for the Gmail and Calendar tools in Fixture-world mode, with the same names and arguments, so that tests and evals never read my real mail or calendar.
57. As the owner, I want MCP servers to receive only the environment variables they need, so that third-party code never sees my other API keys.
58. As the owner, I want the Microsoft 365 server to start outside the repo folder, so that it can't read the repo's `.env` on its own.
59. As the owner, I want the Microsoft 365 server started once at startup, not twice, so that startup is faster and its messages aren't duplicated.
60. As the owner, I want the fake Informer API and the Microsoft 365 stand-in to be able to answer with throttling (429), so that retry behaviour is tested against the failures that happen in reality.
61. As the owner, I want a fake hand-over that records uploads, and the fake Informer API to serve the seeded figures behind Revenue and VAT to pay, so that those features are tested exactly.

### Cost

62. As the owner, I want every model call within a run to start with the same tools and system prompt, so that providers can serve that opening from cache.
63. As the owner, I want "now" in the agent's context to be the time I asked, fixed for the run, so that the opening doesn't change between calls.
64. As the owner, I want Claude models asked to cache the tools and system prompt, so that repeated openings cost about a tenth.
65. As the owner, I want cached tokens recorded in usage logs and eval cost, so that I can see whether caching works, for Gemini as well as Claude.
66. As the owner, I want the tool definitions sent to Gemini cleaned of schema keys it ignores, so that runs don't log seventy warnings.
67. As the owner, I want the deprecation warning from the checkpoint library gone, by moving to a version that fixed it, so that output stays clean.

### Prompts

68. As the owner, I want a new prompt version without the reminder rules, with released versions never changed, so that every trace and eval names exactly the prompt that ran.
69. As the owner, I want an unknown prompt version to stop the agent, so that a typo doesn't run some other prompt under a wrong label.
70. As the owner, I want CLI and eval traces to record the prompt version that actually ran, so that I can compare prompts honestly.

### Evals

71. As the owner, I want eval scenarios asking for Revenue and VAT to pay, passing only with the exact seeded amount and the right tool, so that I know the financial answers are right.
72. As the owner, I want upload scenarios graded on what the fake hand-over received (exactly one upload of the right file after approve, none after reject), so that I measure outcomes, not just tool calls.
73. As the owner, I want an upload scenario where the upload fails, passing only when the answer reports the failure, so that "recovered" means more than "didn't crash".
74. As the owner, I want a scenario that proposes an upload and a VAT question together, where I reject the upload, so that the new Approval behaviour is measured with a real model.
75. As the owner, I want two scenarios for searching past runs, one where the first search finds nothing, so that search recovery is measured.
76. As the owner, I want the outcome grade to count toward passing, so that a run that calls the right tools but uploads the wrong file fails.
77. As the owner, I want a model comparison to show the paired difference in pass rate with a 95% range, and say plainly when the two can't be told apart, so that I don't choose a model on noise.
78. As the owner, I want comparisons to show how often a scenario passed all its repeats, so that reliability is visible, not only averages.
79. As the owner, I want judge-based quality scores labelled as unvalidated, so that I don't over-trust them.
80. As the owner, I want a warning when the judge and the model come from the same provider, so that self-preference risk is visible.
81. As the owner, I want answer-quality averages to stay representative when some runs couldn't be scored, so that dropped runs don't silently skew them.
82. As the owner, I want an expected fact to match regardless of letter case, a forbidden tool call to fail a run on its own, and two calls in the same step not to count as one before the other, so that eval verdicts are correct.

### Tests and housekeeping

83. As the owner, I want every Track B killing test that still applies added to the suite, so that the bugs they guard against can't come back.
84. As the owner, I want comments and docstrings that describe the code as it is (message merging by ID, budget integration, model names), so that the code doesn't mislead the next reader.
85. As the owner, I want a single source for the memory threshold setting, so that changing it in one place changes it everywhere.
86. As the owner, I want the stale memory paragraph in the known-issues notes removed and the old query-rewriting ticket closed as superseded, so that the paperwork matches the code.

## Implementation Decisions

### Order and manual work

- Tickets are numbered in this order: things broken today (Langfuse crash, Google login, Approval failing open, two failures in one step); then the two manual tickets; then safety (Approval semantics, MCP environment allowlist, Google stand-ins, memory writes only on Approval); then the Informer rework and its evals; then run limits and context; then cost and eval statistics; then memory search, cleanups and the remaining killing tests.
- **Manual tickets come first and are the owner's** (`ready-for-human`): (1) run the upload probe on two Purchase invoices that need booking anyway, one PDF and one JPG, and record request, response and what the accountant sees; (2) read the RGS codes of ITtopia's Revenue and VAT ledgers from the real chart of accounts. Building the probe script is an agent ticket that precedes the probe run. The probe (done 2026-10-22) showed v1 can't take a file alone, so the upload doesn't use v1 (ADR-012 amendment); `revenue` and `vat_position` are blocked on the ledger record (done 2026-10-22).

### Startup and observability

- The Langfuse connection check never raises: any failure is a warning that names the base URL, and the run continues untraced.
- Google: a login check at startup, only when the real Google tools are bound. A missing token, or a refresh failing with an invalid grant, deletes the dead token and fails startup with a message naming a new re-login command. The re-login command is the only place a browser opens. The OAuth app stays in Testing; there is no wizard stage.

### Approval (ADR-010 as amended)

- One Approval per step, covering all of that step's Write actions together, all or nothing.
- Only the exact decision "approve" approves; every other value, including empty, rejects.
- On reject: the reads in the step run; each Write action gets a rejection tool message with error status. The tools stage executes only tool calls that have no answer yet, so a rejected Write action can never run.
- A single shared entry point is used by every caller that starts or resumes a conversation. It: validates a resume decision; refuses to resume a conversation with no pending Approval; and, when a new message arrives on a conversation with a pending Approval, answers the pending Write actions as rejected ("the owner moved on without approving") before processing the new message.
- The Approval shows each Write action's tool name and raw arguments, as today. There is no per-tool Approval description: what the owner should know before approving is reported by a read the agent calls first, or made an explicit argument (ADR-012 amendment).

### Run limits

- A model-call counter lives in the graph's state for the run. The agent step increments it; a new user message resets it; a resume does not. At the configured maximum (the existing, currently unused max-iterations setting, default 10), the graph ends the run with an answer stating it hit the step limit. The framework's recursion limit stays as a backstop. The eval harness relies on the same mechanism and records such runs as step-limit results.

### Context (ADR-013)

- State and checkpoints are never trimmed. The trim and its message-removal path are deleted.
- Before each model call, the token count is the previous model call's reported input tokens plus a four-characters-per-token estimate of the messages added since (first call: estimate everything, including the system prompt and tool definitions).
- Above 100k tokens, tool results from earlier steps are replaced in the model's view, oldest first, by a stub giving their approximate size and saying the tool can be called again, until the view is under 50k. User messages and every model message stay; every tool call keeps an answer.
- A tool result over 20k tokens is truncated where tools return, with a marker.
- The warning threshold setting is removed; reductions log their own line.
- Retrieved memory returns at most top-k chunks within the memory budget (10k).

### Memory (ADR-014)

- A new `remember` tool, classified as a Write action, stores one memory in semantic memory. Answers are never ingested automatically; the interactions collection is removed.
- Semantic memory uses cosine distance; existing stores get a one-off re-index. The threshold is a single setting, calibrated on a labelled Fixture-world set (about 10 remembered facts, about 20 queries each labelled with the fact it should find or "nothing").
- The run log records per run: the question, tools called, total usage and cost over all model calls (cached tokens included), and the outcome (completed / step limit / error / rejected). Write failures are logged.
- Past-run search: the separate rewrite model call and its setting are deleted. The episodic tool takes search terms plus optional start and end dates, written by the agent as tool arguments; the semantic tool takes a query the agent writes. Episodic search uses SQLite full-text search ranked by relevance (BM25) with the date filter. An empty result says so plainly, so the agent can try other terms.

### Informer (ADR-012)

- Removed: the overdue-invoice tool, the Payment reminder MCP prompt, and their rules in the system prompt.
- Kept: the Relation and Sales invoice read tools, the trial balance tool, and the administration and chart-of-accounts resources.
- New read tools: `revenue(year, period_from, period_to)` and `vat_position(year, quarter)` (VAT to pay: VAT charged on Sales invoices minus VAT paid on Purchase invoices, quarter = periods 1–3, 4–6, 7–9, 10–12). Both are exact decimal sums over the trial-balance report, returned as decimal strings in EUR, over ledgers chosen **by number** (one VAT ledger has no RGS code), configurable, with defaults from the manual ledger record. Informer reports balance-sheet ledgers year-to-date whatever the start period, so a quarter is computed as year-to-date at its end minus year-to-date at the previous quarter's end. The accountant books the year-end closing inside Q4, so Q4 of a closed year is refused with a message pointing to the accountant. The existing trial balance tool's description is corrected to state the year-to-date behaviour.
- Two new tools on the Informer server: `check_purchase_invoice(path)`, a read returning either the refusal reason or the file name, size and the date of any earlier upload of the same contents; and `upload_purchase_invoice(path, allow_duplicate=false)`, a Write action (never retried) that re-runs every check and hands the file over. Checks: extension PDF; content really is PDF; size under a cap (default 2 MB, a setting); the resolved path is inside the owner's Downloads folder or a subfolder (no escape through symbolic links or `..`). The check tool's description tells the model to call it before proposing an upload.
- The Informer server keeps an upload log, at a path in its settings, with a content fingerprint and date per successful upload. A repeat of earlier contents is refused unless `allow_duplicate` is true, so the Approval itself shows a deliberate re-upload.
- The file reaches Informer through a hand-over transport chosen in the Informer server's settings. The Fixture world sets a recording fake that can be told to fail; no real transport exists yet (a follow-up). With no transport configured, neither upload tool is registered and the server's instructions don't mention uploads; with one, the instructions say it accepts Purchase invoice uploads. No v1 client: the probe showed v1 can't take a file alone and reports errors with HTTP 200.
- The fake Informer API gains: seeded trial-balance data with Revenue and VAT ledgers; a throttling (429) failure mode.

### Fixture world and MCP servers (ADR-011 as amended)

- Seeded stand-ins replace the Gmail and Calendar tools in Fixture-world mode, with the real tools' names and arguments, following the web-search stand-in.
- Each MCP server receives an allowlisted environment: system basics (path, home, Node/npx variables) plus its own settings (Microsoft 365 or Informer settings; the Fixture-world date for stand-ins). The Microsoft 365 server starts with a working directory outside the repo. The existing test that removes the keytar variable in its setup is fixed so it can fail.
- Startup reuses one Microsoft 365 session for loading tools and checking the login.
- The Microsoft 365 stand-in gains a throttling (429) failure mode.

### Cost

- The clock is read once when a run starts and kept in state; the runtime context in the system prompt uses that value for every call in the run.
- Tools are bound sorted by name.
- For Anthropic models, the end of the tool definitions and the system prompt are marked cacheable.
- Usage logging and eval cost record cached input tokens separately; pricing applies the cached rate.
- Tool schemas are normalised when bound: `$schema` and `additionalProperties` are dropped (with a comment that the Microsoft 365 download tool's `false` is dropped deliberately).
- The checkpoint library is upgraded to the version that fixes its deprecation warning, provided the lock file resolves with the pinned LangGraph.

### Prompts

- A new prompt version v4 without the Overdue invoice and Payment reminder rules, composed from shared pieces like v3; released versions keep their fingerprints and are never edited. The default prompt version moves to v4.

### Evals

- The overdue-reminder capstone scenarios are replaced by three groups: financial questions (exact amounts plus right tool), uploads (outcome grade from what the fake hand-over recorded; approve, reject, failure-reported; the approve scenario expects the check before the upload), and one mixed step (upload plus VAT question, upload rejected, read still answered). Two past-run search scenarios are added.
- An outcome score is added beside the trajectory score and counts toward passing for scenarios that declare an expected outcome.
- Comparison reports: paired pass-rate difference with a 95% range clustered by scenario, a "can't tell apart" verdict when the range includes zero, and pass^k. Judge scores are labelled unvalidated; a same-provider judge gets a warning. Answer-quality averages report how many runs were scored and are not computed over a silently shrunk set.
- The old real-model comparison ticket (ticket 18 of the Phases 5–7 spec) is blocked by the new eval tickets.

## Testing Decisions

- **A good test drives behaviour through a seam and asserts on what the owner or the model would observe** (messages, interrupt payloads, tool results, recorded uploads, reports), never on internal structure. Every new test must fail on a plausible wrong implementation: Track B found tests whose setup removed the very condition they checked, and tests whose data couldn't tell two behaviours apart. Use data that distinguishes the right behaviour from the obvious wrong one, and non-default settings where a default would hide a bug.
- **Seams (all existing):**
  - the graph built with an injected scripted model: Approval semantics, the shared entry point, step limit, context reduction, the stable system prompt and tool order, `remember`, the memory tools. Prior art: the graph tests and the scripted-model fixture; killing tests k10, k11.
  - the Informer MCP server over an in-memory MCP session against the fake Informer API: `revenue`, `vat_position`, the check and upload tools (path, type, size, duplicate checks; what the fake hand-over recorded; neither tool registered without a transport). Prior art: the Informer server tests; k31.
  - the CLI driver: Langfuse down, Google login failure at startup, second Approval, flush, tracing after resume. Prior art: the CLI fixture tests and the CLI harness used by k15, k19, k20.
  - the eval harness on the Fixture world: new scenarios, the outcome grade, comparison statistics, the judge warnings. Prior art: the eval tests; k58, k59, k61, k65.
  - the MCP server specs each server builder returns: environment allowlist and working directory. Prior art: the loader tests; k92.
  - the memory stores with fixed embeddings: full-text search with dates, cosine similarity, the calibration set. Prior art: the memory tests and notebook 05's fixed-embeddings helper.
- **Killing tests** come from the Track B folder of verified tests and are added to the suite as they are, unless the decision they guard changed: k03, k05, k06, k07, k10, k11, k15, k19, k20, k31, k38, k39, k41, k42, k48, k58, k59, k61, k92 land as they are (k92 goes green with the allowlist); k18 and k65 are rewritten against the new step limit; k23, k25 and k90 are dropped and replaced by tests of ADR-013's guarantees (the question is kept, no tool call is left unanswered, the view is never empty, nothing is removed from state); k54 and k55 are dropped with the overdue tool.
- **Required named tests beyond the killing tests:** a rejected Write action never executes; a reject still runs the reads in the same step; a new message on a pending Approval rejects it and leaves a valid history; a resume with no pending Approval is refused; the step counter survives a resume and resets on a new message; the system prompt is byte-identical across all model calls in a run; tools are bound in name order; an upload outside Downloads, through a symbolic link, of a wrong type, of mislabelled content, or over the cap is refused by the check and again by the upload; a repeat upload is refused unless `allow_duplicate` is true, and the check reports the earlier date; with no transport configured neither upload tool is listed; the Fixture world binds no real Google tool; no MCP server environment contains an unlisted variable.
- **Validation per ticket:** the full test suite passes; the default suite never touches real services.

## Out of Scope

- The MCP SDK 2.0 upgrade (D1): blocked until the LangChain MCP adapters support it; kept in the register as a watch item.
- Getting Purchase invoices from email attachments or from vendors' websites: future sources; the upload only takes a local file.
- The real hand-over transport for Purchase invoices (most likely Informer's incoming e-mail address): a follow-up feature; this spec builds the upload tools against a fake transport only.
- Per-call Approval (approving some Write actions of a step and not others).
- A cost budget in money; the step limit is the only run budget.
- Publishing the Google OAuth app to Production, and a Google stage in the setup wizard.
- Calibrating the LLM judge against the owner's labels.
- Writing out each prompt version in full.
- Encrypting the local run log.
- Filling in the placeholders of ADR-001 to ADR-003 (the owner's own writing).
- Overdue-invoice and Payment reminder features of any kind.

## Further Notes

- **VAT returns are quarterly** (confirmed by the owner, 2026-10-22).
- **Informer v1 can't take a file alone** (probe, 2026-10-22) and reports validation errors with HTTP 200. Uploads to the real administration are real records the accountant sees; never upload to it from a test.
- **The ADR log is not tracked in git**: ADR-012 to ADR-014 and the 2026-10-22 amendments exist on disk only.
- **Unattended run in Cursor:** each ticket is implemented by Haiku or Composer 2.5. Haiku is much cheaper while the implementer's context stays under 100k tokens and much more expensive than Composer 2.5 above it, so each ticket carries a `Model:` hint from its expected context size: **Haiku** when the ticket touches at most two source modules and one test file and lands or follows an existing test; **Composer 2.5** when it may exceed 100k (it spans the graph, the CLI and the eval harness together, builds a new subsystem or stand-in, or needs several red-green cycles over large files). When unsure, Composer 2.5. The orchestrator and the final code review should run on a strong model.
