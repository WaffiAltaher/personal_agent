# Review findings register (Track B, concepts 1–8)

Findings from the Track B notebooks (concepts 1–5, `notebooks/01`–`04`) and Lesson 7's experiments (concepts 6–8, `notebooks/05`, Part A). This is a register, not tickets yet: each item becomes a ticket under this folder once its design question (if any) is decided.

Every item is verified by running code unless marked *read-only*. Severity: **bug** = user-visible · **latent** = will bite under a reachable condition · **cosmetic**. Fix: **mech** = mechanical · **decision** = needs the owner's call (grouped at the end).

Noise fixes: fix the cause when the message points at something we control; route it to a log file when it's legitimate log output in the wrong place. Never raise a log level or add a warning filter just to silence output.

Do the notebooks' Part C drills **before** any of the test gaps below are closed. Adding a killing test to `tests/` turns its drill's answer from "survived" into "caught", so the drill teaches nothing after that. *(2026-10-22: the owner treats all drills, notebooks 01–11, as done; tickets are not gated on them.)*

## A. Test gaps: the mutant survives today, and a killing test is ready

All killing tests are in `notebooks/killing_tests/`. Each is verified to pass on the real code and fail on its mutant.

| Mutant | What gets through | Killing test | Severity of the bug it would let in |
|---|---|---|---|
| M3 | `errors` loses its reducer; two failures in one batch crash the run | `k03_two_failures_in_one_batch` | bug (crash) |
| M5 | HTTP 500 not retried | `k05_http_status_boundaries` | latent |
| M6 | no exponential backoff | `k06_backoff_grows` | cosmetic/latent |
| M7 | the fallback catches nothing | `k07_fallback_catches_a_crash` | bug (crash on a lower-layer bug) |
| M10 | a rejected mixed batch leaves an unanswered tool call | `k10_reject_answers_every_call` | bug (provider error) |
| M11 | anything except "reject" approves (fails open) | `k11_anything_but_approve_rejects` | bug (safety) |
| M15 | the CLI handles only the first approval | `k15_cli_second_approval` | bug (silently skipped action) |
| M18 | no step limit in the CLI | `k18_step_limit` | latent (cost) |
| M19 | no flush before exit | `k19_flush_before_exit` | latent (lost traces) |
| M20 | the resume isn't traced | `k20_resume_is_traced` | latent (half a trace) |
| M23 | trim keeps the oldest messages | `k23_trim_keeps_the_newest` | bug above the hard limit |
| M25 | the budget node removes every message | `k25_node_removes_only_what_trim_drops` | bug above the hard limit |
| M12 | the rejection message stops steering the model | none: needs an **eval** (concept 14) | latent |
| M31 | a per-minute 429 from Informer is reported as permanent | `k31_per_minute_429_is_transient` | latent |
| M38, M40 | a released prompt version's text changes (M40: editing v2 silently changes v3) | `k38_released_prompt_versions_never_change` | latent (traces mislabelled) |
| M39 | an unknown `PROMPT_VERSION` runs some other prompt | `k39_unknown_prompt_version_is_refused` | latent |
| M41 | eval traces always tagged `prompt:v3` | `k41_eval_traces_name_the_prompt_that_ran` | latent (wrong data) |
| M42 | CLI traces don't record the prompt version | `k42_cli_traces_record_the_prompt_version` | latent (wrong data) |
| M48 | Graph's 429 not treated as transient | `k48_throttled_graph_call_is_transient` | latent |
| M54 | Clients sorted by name, not largest debt first | `k54_largest_debt_comes_first` | latent |
| M55 | a concept (never issued) invoice counts as overdue | `k55_a_concept_is_never_overdue` | bug (reminder for an unsent invoice) |
| M58 | an ordering constraint is met by two calls in the same turn | `k58_same_turn_is_not_before` | latent (false eval pass) |
| M59 | a run that calls a forbidden tool can still pass | `k59_*` | latent (false eval pass) |
| M61 | expected facts matched case-sensitively | `k61_*` | latent (false eval fail) |
| M65 | eval step limit 40 → 400 goes unnoticed | `k65_*` | latent (cost) |
| M56, M57 | capstone rules in the prompt (address rule, quote exactly) reversed or removed | none: needs an **eval with an outcome grader**, or the rule moved into code (F6) | latent |

**Red on purpose** (fail on the real code today; they are bug reports, not mutant killers): `k90_trimmed_history_is_valid` (C1–C3) and `k92_*` (F3).

## B. Code issues, concepts 1–5 (notebooks 01–04)

| # | Issue | Where | Verified | Sev. | Fix |
|---|---|---|---|---|---|
| B1 | Reject is all-or-nothing per batch. A rejected batch tells the model the *user* rejected the reads too, and rejections carry `status="success"` | `human_review_node` | nb 03 Exp 5 | latent | decision (a) |
| B2 | `Command(resume=None)` crashes inside LangGraph 1.1.6 (`UnboundLocalError`) instead of rejecting | caller of resume | scratch run | latent (future frontends) | mech: validate the decision before resuming |
| B3 | `recursion_limit` resets on every resume, so loops through approvals are uncapped | `cli.py` config | nb 04 Exp 7 | latent | decision (b) |
| B4 | The fallback's ToolMessage has no `status="error"` and always says "try again later" | `tools_with_fallback` | nb 02 Exp 5 | cosmetic | mech |
| B5 | Resuming an unknown `thread_id` silently starts an empty run; the real request stays parked | callers of resume | nb 03 Exp 3 | latent (future frontends) | mech: check `aget_state(cfg).interrupts` first |
| B6 | A new message on a paused thread drops the pending approval and leaves an unanswered tool call | callers of `ainvoke` | nb 03 Exp 4b | latent (future frontends) | decision (a) |
| B7 | `log_run_to_memory` logs the last call's usage only, never `cost_usd` (`evals/pricing.py` could supply it), always `success=True`, and swallows errors without logging | `graph.py` | nb 04 Exp 4; rest read-only | latent (wrong data) | mech, plus decision on "success" |
| B8 | Five retired Gmail/Calendar tools are still bound: part of the ~80% tool-definition overhead on every call | `tools/__init__.py` | nb 04 Exp 2 | latent (cost) | decision (c) |
| B9 | CLI tracing wiring has no tests (resume, flush, step limit): see A, M18–M20 | `cli.py` | nb 04 Part C | n/a | mech (tests in A) |
| B10 | No prompt caching: every model call re-sends the ~4.3k-token tools + system prefix at full input price (cached reads are 10%, `evals/pricing.py`). No `cache_control` for Anthropic models; whether Gemini's implicit caching hits is unchecked (Exp 3 prints `input_tokens` only, which includes cached tokens) | `agent_node` / model setup | nb 04 Exp 3; grep (no caching config in `src/`) | latent (cost) | decision (i) |

## C. Code issues, concepts 6–8 (from the Lesson 7 session; Exp N = `notebooks/05`, Part A)

| # | Issue | Where | Verified | Sev. | Fix |
|---|---|---|---|---|---|
| C1 | The trim drops the user's question first | `trim_messages` via `check_context_budget` | Exp 2 (sweep: only budgets fitting everything are valid) | bug above the limit | decision (d) |
| C2 | The trim can orphan a ToolMessage | same | Exp 2 sweep (27 budgets) | latent | mech if it stays a trim; else (d) |
| C3 | One oversized tool result makes the node remove *every* message, permanently | `check_context_budget` | Exp 4 | bug | decision (d) |
| C4 | Wrong technique: it trims turns, but the pressure is tool results inside one turn | design | Exp 3, Exp 5 | design | decision (d) |
| C5 | Token count skips `tool_calls` arguments | `TokenCounter`, `trim_messages` | Exp 1 | latent | mech |
| C6 | Count misses the system prompt and tool definitions (= Lesson 5's finding) | `check_context_budget` | nb 04 Exp 5: 397 vs 4,801 | latent | mech-ish: use last `usage_metadata` + delta |
| C7 | Limits sized to the window, not quality or cost. Warning only logs. Docstring says Gemini 2.0 | `config.py`, `budget.py` | read-only | latent | decision (e) |
| C8 | Trims to exactly the hard limit, so it fires again next round | `check_context_budget` | read-only | latent | mech |
| C9 | "Never drop the system message" never applies (it isn't in state); id-less messages silently skipped | `trim_messages`, `check_context_budget` | read-only | cosmetic | mech |
| C10 | Retrieved memory is never budgeted; `memory_top_k`, `trim_memory_results`, `MEMORY_BUDGET` unused | `tools/memory.py`, `budget.py` | grep | latent | mech + decision (e) |
| C11 | `test_hard_limit_triggers_trim` only asserts "shorter" | tests | = A: M23, M25; red test `k90_trimmed_history_is_valid` | test gap | mech |
| M1 | Threshold 0.7 means cosine ≥ ~0.79 (Chroma l2 is squared; mapping assumes it isn't); scores can be negative | `SemanticMemory` | Exp 7 | latent | decision (f) |
| M2 | Episodic search is a substring LIKE | `search_runs` | Exp 6 | known limitation | decision (g) |
| M3 | LIKE wildcards `%`/`_` not escaped | `search_runs` | scratch run | latent | mech |
| M5 | Every answer, right or wrong, goes into semantic memory: feedback loop, stored prompt injection | `log_run_to_memory` | read-only | latent (security) | decision (h) |
| M6 | Plaintext client data in `data/episodic.db`; every interaction sent to the embeddings API | memory | read-only | policy | decision (h) |
| M7 | Two sources of truth for the threshold (signature default 0.7 vs setting) | `semantic.py` | read-only | cosmetic | mech |
| R1 | Rewrite is a single-call workflow; a bad rewrite is never recovered | `recall.py` | Exp 9 | latent/design | decision (g) |
| R2 | A malformed rewrite reply falls back silently to the literal query (finds nothing) | `rewrite_query` | Exp 8 | latent | decision (g) |
| R3 | `docs/known_issues.md` memory paragraph not removed; ticket 07's last box unchecked | docs | read-only | cosmetic | mech, after (g) |
| X1 | `AgentState` comment says add_messages "appends"; it merges by ID | `graph.py` | read-only | cosmetic | mech |
| X2 | `budget.py` docstring says graph integration is "deferred"; it's integrated | `budget.py` | read-only | cosmetic | mech |

(C-section items M4 = B7 and C6 = Lesson 5's finding, merged.)

## D. Code issues, concepts 10 and 12 (from the Lesson 8 session; Exp N = `notebooks/06`)

| # | Issue | Where | Verified | Sev. | Fix |
|---|---|---|---|---|---|
| D1 | MCP SDK is on the 1.x line (`mcp` 1.27.2, pinned `<2`), which speaks spec 2025-11-25. `mcp` 2.0 (2026-07-28) supports the 2026-07-28 revision and still serves 2025-era clients; 1.x is now in maintenance mode (security fixes only). **Blocked:** `langchain-mcp-adapters` 0.3.2 (latest) requires `mcp<2` (its PR #588, "constrain MCP SDK to v1"). Code impact when unblocked: `FastMCP` → `MCPServer` (decorator API unchanged), test helpers `ClientSession` / `create_connected_server_and_client_session` → `Client`, plus the adapters upgrade; no Roots, Sampling or Logging in use | `pyproject.toml`, `src/informer_mcp`, `src/fixture_world/ms365.py`, `tests/informer_server` | PyPI + SDK release notes, 2026-10-15; grep | latent (maintenance) | mech, once the adapters support `mcp` 2 |

## E. Live-run issues (from manual live-path testing, ticket 17; run of 2026-10-17, `--debug`, real Gmail)

| # | Issue | Where | Verified | Sev. | Fix |
|---|---|---|---|---|---|
| E1 | A dead Google refresh token (`invalid_grant`) raises `RefreshError` from `creds.refresh()`; the browser re-auth is only reached when there is no refresh token at all, so the user must delete `credentials/token.json` by hand. The docstring says Testing-mode tokens expire after "7 days … without use"; they expire 7 days after issue regardless of use | `auth/google.py` | live run; `token.json` expiry 2026-06-02 | bug (all Gmail/Calendar tools fail) | mech (catch `RefreshError` → delete token → re-auth) + decision (j) |
| E2 | Google tools have no equivalent of MS365's `LoginCheck`: no startup check, and the error ToolMessage is the bare exception without the re-auth command. The model only stopped because the prompt told it to | `tools/gmail.py`, `tools/google_calendar.py`, `tools/__init__.py` | live run (ToolMessage [3]) | latent | mech: same pattern as `LoginCheck` |
| E3 | ~70 lines of `Key 'additionalProperties' / '$schema' is not supported in schema, ignoring` per run, logged by `langchain_google_genai` while converting tool schemas for Gemini. 38 tools carry `$schema` and 39 carry `additionalProperties` (37 MS365 + Tavily, which has only `additionalProperties`); every `additionalProperties` is `true` (the JSON Schema default) except `ms365_download-bytes` (`false`, which Gemini can't express anyway). Still warns in the latest `langchain-google-genai` (4.4.2) | `graph.py` (`bind_tools`) | live run; scratch probe over the real bound tools; 4.4.2 source `_function_utils.py:122` | cosmetic | mech: normalise schemas at bind time (not in `mcp_loader`: Tavily isn't MCP) — drop `$schema` and `additionalProperties`, with a comment that `download-bytes`' `false` is dropped deliberately |
| E4 | `[ms365-mcp] Ignored 1 variable(s) from .env: MS365_MCP_EXPECTED_USERNAME`, printed twice. The npx server reads our `.env` from its cwd on its own; harmless, since we pass the variable through `env`. Twice because startup launches the server twice (`get_tools`, then `_check_login`, each its own session) | `ms365_mcp.py`, `mcp_loader._load_server` | live run; scratch run counting `stdio_client` launches at startup (MS365 ×2, Informer ×1) | cosmetic | mech: spawn the server with a `cwd` outside the repo |
| E5 | `LangChainPendingDeprecationWarning` (`allowed_objects`) on import: `langgraph-checkpoint` 4.0.1 builds `Reviver()` at module level without `allowed_objects` (`jsonplus.py:45`), so our code can't pass one. Fixed in 4.3.0 (`Reviver(allowed_objects="core")`, `jsonplus.py:47`) | upstream (langgraph-checkpoint) | live run; 4.0.1 and 4.3.0 source | cosmetic | mech: upgrade `langgraph-checkpoint` to ≥ 4.3.0; check `uv lock` resolves with langgraph 1.1.6 |
| E6 | Langfuse being unreachable crashes every CLI run before the agent starts (`httpx.ConnectError: [Errno 61] Connection refused`), so it looks like a broken tool connection, though no tool was ever called. The CLI means to warn and continue ("observability failing shouldn't block the agent"), but `Langfuse.auth_check()` (4.1.0) returns `False` only on `AttributeError` and raises on everything else (refused connection, bad keys, no project), so the warning branch is dead. Trigger on 2026-10-21: Docker not running, so nothing on `localhost:3000` (`LANGFUSE_BASE_URL`). Asked: "How does my calender looks like for next week Monday? check both work and personal agendas", `google_genai:gemini-3.8-flash`, `--debug` | `tracing.verify_connection`, `cli.py:138` | live run (traceback); `curl` to `:3000` refused; `docker ps` (no daemon); langfuse 4.1.0 `auth_check` source | bug (whole CLI blocked by a tracing outage) | mech: catch the exception in `verify_connection`, return `False`, and include the base URL in the warning |

## F. Code and eval issues, concepts 11–15 (notebooks 07–11, Part A experiments and Part D scorecards)

| # | Issue | Where | Verified | Sev. | Fix |
|---|---|---|---|---|---|
| F1 | The system message isn't stable within a run: the runtime context carries the current time, so every model call differs after the tool definitions. Blocks prompt caching (B10) and preserved thinking | `graph.py` (`build_runtime_context`) | nb 07 Exp 2–3, M43 | latent (cost) | decision (i) |
| F2 | v3 is composed from v2's lines, so editing v2 silently changes v3 | `prompts` | nb 07 M40 | latent | decision (k) |
| F3 | `MS365_MCP_USE_KEYTAR` in the shell reaches the MS365 server; the existing test deletes it in setup, so it can't fail (red test k92) | `ms365_mcp.py`, its test | nb 08 Part C | latent (security) | decision (l) |
| F4 | The MS365 server process sees our whole environment and `.env`; nothing limits it | `ms365_mcp.py` | nb 08 Exp 5–6 | latent (security) | decision (l); see E4 |
| F5 | The fakes lack a 429 failure mode (MS365 stand-in answers 503 only; same for Informer, M31) | `fixture_world` | nb 08, nb 06 | test gap | mech |
| F6 | The capstone's rules (address, quote exactly, report don't guess) live only in the prompt; no test can see them, since the scripted model does the join itself | `prompts`, capstone | nb 09 M56/M57; nb 11 design drill | latent | decision (m) |
| F7 | Matching mail to Clients can't succeed on the seed data | `fixture_world` seed | nb 09 Exp 3 | test gap | mech |
| F8 | No outcome grader: no eval reads the Drafts of a scored run (prototype grader in nb 10 cell 109) | `evals` | nb 10 Exp 1 | latent | decision (m) |
| F9 | The recovery metric only means "didn't crash" (M60 is equivalent) | `evals/trajectory.py` | nb 10 Exp 2 | latent | decision (m) |
| F10 | RAGAS means aren't representative when runs drop out | `evals` | nb 10 Exp 6 | latent (wrong data) | mech |
| F11 | No statistics: no interval, paired difference or pass^k; 18 scenarios × 3 repeats can't tell close models apart | `evals compare` | nb 10 Exp 8 | latent | decision (n) |
| F12 | The judge has never been calibrated against the owner's labels | `evals` | nb 10 scorecard | latent | decision (n) |
| F13 | Same-family judge (e.g. Opus judging Sonnet) isn't warned; only an identical name is | `evals compare` | nb 10 Exp 7 | cosmetic | mech: compare the provider prefix too |
| F14 | ADR-001, 002, 003 have placeholders (no dates; 001's reasoning, 002's consequences, 003's reasoning and consequences) | `docs/ARCHITECTURE_DECISIONS.md` | nb 11 Exp 7 | docs | owner writes them (Lesson 13 practice) |

## Design decisions for the owner

- (a) Approval granularity: per call instead of per batch? And what may happen to a thread while it's paused? (B1, B6)
- (b) A run-level step/cost budget that survives resumes? (B3)
- (c) Unbind the retired Google tools? (B8)
- (d) Shrinking context: model's view vs state; clear tool results vs trim vs summarise; what to do with one oversized result (C1–C4)
- (e) What the context and memory limits should be, and what they trigger (C7, C10)
- (f) Similarity metric and how to calibrate the threshold (M1)
- (g) Episodic search and rewriting: FTS/BM25, embeddings, or a retrieval sub-agent; decide with eval evidence (M2, R1–R3)
- (h) What is written to memory, where, and whether writes need approval (M5, M6)
- (i) Prompt caching: explicit `cache_control` for Anthropic, verify Gemini's implicit caching, and keep the prefix stable (tool order, prompt version) so it can hit (B10)
- (j) Google re-authentication: when the refresh token is dead, open the browser mid-run, or fail with a message naming the re-auth command and add a Google step to `setup_wizard.sh`? And publish the OAuth app to Production so the token stops expiring every 7 days? (E1, E2)
- (k) Prompt versions: write each released version out in full, or keep composing them? (F2)
- (l) MCP server environment: strip known-bad variables, or pass an allowlist? (F3, F4, E4)
- (m) Capstone rules: keep them in the prompt and add an outcome grader, or move them into code? (F6, F8, F9, M56, M57)
- (n) Eval statistics and judge calibration (F11, F12)

## Decisions taken (grilling, 2026-10-22)

- **Scope:** every item in this register is fixed; drills are not a gate.
- **(a) part 1, approval granularity (B1):** one Approval per batch, covering its Write actions together (all-or-nothing). On reject, the reads in the batch still run; only the Write actions get rejection ToolMessages, with `status="error"`. The tools node must run only calls that have no answer yet, so a rejected Write action can never execute (new test, alongside k10/k11).
- **(a) part 2, new message on a paused thread (B6):** an implicit reject. Pending Write actions get rejection ToolMessages ("the user moved on without approving"), then the new message is processed. Enforced in one shared helper that every caller of `ainvoke`/resume uses; B2 (validate the decision) and B5 (check `aget_state(cfg).interrupts` before resuming) live there too.
- **(b) step budget (B3):** a model-call counter for the run in graph state, incremented by `agent_node`, reset by a new user message, not by a resume. At `settings.max_iterations` (today unused, default 10) the graph ends with a "stopped: step limit" answer; CLI and eval harness both rely on it. `recursion_limit` stays as a backstop. No USD budget. k18 and k65 are rewritten against the new limit.
- **(c) Google tools (B8):** kept, not retired. Supersede the "Gmail + Google Calendar are retired" line in `ARCHITECTURE_DECISIONS.md` and `MASTER_PLAN.md` 2.3/2.4: the agent covers ITtopia (MS365, Informer) plus the owner's personal Google mail and calendar. B8 closes as "not retired" (cost is handled under (i)). E1, E2, (j) go ahead.
- **New context: Informer has exactly two uses.** (1) Questions about the financial situation (revenue, VAT (BTW) to pay, …). (2) Uploading a purchase invoice as just a file (PDF or image), with no details; the accountant books and tags it in Informer. The overdue-invoice / payment-reminder assumptions of the Phases 5–7 build are wrong.
  - API facts (OpenAPI specs fetched 2026-10-22 from `api.informer.eu/docs/v1/api-docs.json` and `/v2/`): v1 `POST /invoice/purchase/` takes JSON with no field marked required and a `pdf` field ("Base64 encoded pdf file"); images aren't mentioned anywhere in v1. v2 `POST /invoices/purchase` requires `relation_id`, `invoice_date`, `number`, `vat_option`, `lines`, so it can't do a file-only upload. Our client is pinned to `https://api.informer.eu/v2`. Neither version has a VAT-return endpoint; v2 has `/reports/balance`, `/reports/column-balance`, `/vat`, `/ledgers`.
- **Overdue invoices and Payment reminders are removed entirely:** `list_overdue_invoices`, the `payment_reminder` MCP prompt, their rules in the system prompt (a new prompt version v4; released versions never change), the `overdue-reminders-*` eval scenarios, and the glossary terms (removed 2026-10-22). Findings that exist only because of them are dropped: k54, k55, M56/M57, F7, and the capstone angle of F6/F8/F9. The plain read tools stay for financial questions: `list_relations`, `get_relation`, `list_sales_invoices`, `get_sales_invoice`, `trial_balance`, and the resources.
- **Purchase invoice upload, file source:** a local file path only. The tool reads the file itself; its bytes never pass through the model. Two future sources are **out of scope** for this ticket set (the owner is still deciding whether they are safe and possible): an email attachment, and downloading the invoice from a vendor's website. Design the upload so each future source only has to produce a local file and then reuse the same upload.
- **Purchase invoice upload, v1 behaviour:** a spike ticket goes first. The executor builds `scripts/informer_upload_probe.py` (v1 `POST /invoice/purchase/`, file only); the owner runs it on two purchase invoices that need booking anyway, one PDF and one JPG, and records the request, the response, and what the accountant sees in Informer. The upload implementation and its fake are blocked on that record. If a JPG is rejected, the tool converts images to PDF locally before uploading.
- **Financial questions:** two new read tools in the Informer MCP server that do the arithmetic in code (exact Decimal sums, unit-tested against the fake): `revenue(year, period_from, period_to)` over the revenue ledgers, and `vat_position(year, quarter)` (VAT charged minus input VAT). `trial_balance` stays for every other question; another question is promoted to a tool only when an eval shows the model getting it wrong. The RGS codes of ITtopia's revenue and VAT ledgers come from the real chart of accounts (`informer://ledgers`) in a short manual check, not assumed; the tools are blocked on it.
- **Eval scenarios replacing the capstone:** three groups. (1) Financial questions graded on exact facts (exact amounts from a seeded column balance with revenue and VAT ledgers) plus the right tool. (2) Upload graded on the outcome: the fake Informer records uploads; pass = exactly one upload with the named file's bytes after approve, none after reject, and a failed upload (503/422) reported in the answer (gives "recovered" a real meaning: F9). (3) A mixed batch (upload + VAT question) exercising B1: the read runs even when the upload is rejected. The outcome grader becomes an `outcome` score in `score_trajectory`'s caller and counts toward `passed` (closes F8).
- **(d) shrinking context (C1–C4, C8):** shrink the model's view, never state. Above the threshold, old tool results (earlier rounds) are replaced in the view by a stub ("[result cleared, ~N tokens; call the tool again if needed]"); user messages and every AIMessage stay, and every tool call keeps an answer. A tool result over the per-result cap is truncated at the tool boundary with a marker. The RemoveMessage trim is deleted. k23/k25/k90 are moot; replaced by tests of the new guarantees (question kept, no orphan, never empty). Clearing fires only above the threshold (it breaks a cached prefix: see (i)).
- **(e) limits (C5–C8, C10, X2):** count = last `usage_metadata.input_tokens` + `len//4` of messages added since. Clearing threshold 100k for every model, clearing down to 50k (hysteresis). Per-tool-result cap 20k (`TOOL_RESULTS_BUDGET`). The warning setting goes away. Memory retrieval returns at most `memory_top_k` chunks within `MEMORY_BUDGET` (10k) via `trim_memory_results`. Stale docstrings fixed.
- **(h) memory writes (M5, M6, B7):** semantic memory is written only on an explicit request, through a new `remember` tool wrapped as a Write action (approved per memory). Answers are never auto-ingested. The episodic log stays local as a run log (question, tools used, run totals of usage and cost, outcome: completed / step limit / error / rejected); M6 is accepted for the local disk. B7 becomes: log the run's totals (not the last call's), `cost_usd`, the real outcome instead of `success=True`, and log errors instead of swallowing them.
- **(f) similarity (M1, M7):** the semantic collection switches to cosine space (`hnsw:space: cosine`; one-off re-index). The threshold lives only in settings. It is calibrated on a labelled Fixture-world set (~10 remembered facts, ~20 queries labelled "should find X" / "should find nothing"), pinned as a test. The `interactions` collection is dropped (its only writer, auto-ingest, is gone under (h)).
- **(g) episodic search and rewriting (M2, M3, R1–R3):** the hidden rewrite model call (`recall.py`, `MEMORY_REWRITE_MODEL`) is deleted; the main agent writes the search itself as tool arguments: `retrieve_episodic_memory(terms, since=None, until=None)` and `retrieve_memory(query)`. Episodic search becomes SQLite FTS5 ranked by BM25, with a date filter (no LIKE, so no wildcard escaping). An empty result is recovered by the agent loop (it tries other terms). A retrieval sub-agent (the owner's earlier `known_issues.md` note) was considered and not chosen: several model calls per lookup within a 10-call step budget. Two eval scenarios: "what did I ask about VAT last week?", and one whose first search finds nothing. R3: remove the `known_issues.md` memory paragraph and close ticket 07 as superseded.
- **(i) prompt caching (B10, F1):** (1) read the clock once per run, keep it in state, so the system prompt is identical within a run; (2) sort tools by name; (3) Anthropic: `cache_control` at the end of tools + system prompt; (4) record the provider's cached-token count in the usage log and eval cost, and check Gemini's implicit caching with one eval run.
- **(j) Google login (E1, E2):** when the real Google tools are bound (real CLI runs only), startup checks the Google login. A missing or dead login (`RefreshError`/`invalid_grant`: delete the dead token) **fails startup** with a message naming a new re-login command (e.g. `python -m agent.auth.google`). No browser ever opens mid-run. No wizard stage; the OAuth app stays in Testing (owner's call). The docstring's "7 days without use" is corrected (7 days after issue).
- **New finding G1, Fixture world uses real Google:** `FIXTURE_LOCAL_TOOLS` swaps only web search, so evals, `--fixtures` and any test through it bind the **real** Gmail and Calendar tools (real personal data into eval results, traces and judge calls; results depend on the inbox). Decision: add seeded Fixture-world stand-ins for the Gmail and Calendar tools (same names and arguments, like `fixture_web_search`). Evals, `--fixtures` and tests then never need a Google login, so (j)'s check never applies there.
- **(k) prompt versions (F2):** keep composing versions from shared pieces; k38's per-version fingerprints catch accidental changes. v4 (without the reminder rules) is composed the same way.
- **(l) MCP server environment (F3, F4, E4):** allowlist for both servers: system basics (`PATH`, `HOME`, Node/npx variables) plus the server's own settings (`MS365_MCP_*` / `INFORMER_*`, `FIXTURE_WORLD_TODAY` for stand-ins). MS365 starts with a `cwd` outside the repo so it can't read `.env`. The existing keytar test's setup is fixed so it can fail (k92 goes green).
- **(n) eval statistics and judge (F11, F12, F13):** `compare` gets the paired pass-rate difference with a 95% range clustered by scenario (nb 10 Exp 8's formula), a plain "can't tell these apart" verdict when the range includes zero, and pass^k. The judge is not calibrated now; RAGAS scores are labelled "unvalidated LLM judge" in reports. F13: warn when judge and model share a provider.
- **D1 (mcp 2.0):** not in this ticket set; stays here as a watch item until `langchain-mcp-adapters` supports `mcp` 2. Re-checked 2026-11-13: the latest adapters release is still 0.3.2 and still requires `mcp<2`; still a watch item.
- **ADRs written 2026-10-22:** ADR-012 (Informer's two uses), ADR-013 (shrink the view, never state), ADR-014 (memory written only on approval); amendments to ADR-004 (Google kept), ADR-010 (Approval semantics), ADR-011 (Google stand-ins). F14 (ADR-001–003 placeholders) stays the owner's, outside this ticket set.
- **Upload safety (Q28; amended by Q36–Q37 below):** the upload tool accepts only `.pdf`, `.jpg`, `.jpeg`, `.png`, under a size cap (e.g. 10 MB), whose content really is that type, and only inside `~/Downloads` or any subfolder of it, checked on the resolved path (no escape via symlink or `..`). Anything else is refused before Approval. The Approval prompt shows the file name, folder, type and size, not just the path.
- **Duplicate uploads (Q29; amended by Q37 below):** a local upload log (next to the episodic database) records a fingerprint of each uploaded file's contents with the date. A repeat of the same contents shows a warning in the Approval prompt ("already uploaded on <date>"); the owner can still approve.
- **Approval description per tool (note for the upload ticket; dropped by Q37 below):** `human_review_node` today shows only the raw tool arguments. Showing file details and the duplicate warning needs a way for a tool to describe its own Approval (a per-tool hook, with the raw arguments as the default).
- **Other notes:** M12 (the rejection message stops steering the model) is covered by eval scenario group 3; it needs no ticket of its own. E4's double MS365 launch at startup (`get_tools`, then the login check) goes in the MS365 cleanup ticket ("reuse one session"). `vat_position` assumes quarterly VAT returns. The old ticket 18 (real model comparison, `.scratch/complete-phases-5-7/`) is blocked by the new eval tickets. `docs/` is untracked in git, so the ADRs live on disk only.
- **Ticket layout (Q27):** this folder holds `findings.md` (the source register), a `spec.md`, and one file per ticket in `issues/NN-<slug>.md`. One ticket per coherent change, not per finding. Each ticket has `Status:` and `Blocked by:` lines and a `Type:` of `task` (an executor can do it) or `manual` (the owner's: the upload probe run, the revenue/VAT ledger RGS check), and lists the findings it closes and the killing tests it adds. Mechanical leftovers (B4, E3, E5, E6, X1, C9, M7, F5, F10) are grouped into small cleanup tickets by module.
- **Ticket order (Q30):** (1) things broken today: E6, E1/E2, M11, M3; (2) the two manual tickets, early; (3) safety: Approval semantics (B1, B2, B5, B6), MCP environment allowlist (F3, F4), Google stand-ins (G1), memory writes only on approval (M5); (4) the Informer rework: remove the reminder work, `revenue`/`vat_position`, upload, new eval scenarios with the outcome grader; (5) step budget, context clearing, limits; (6) prompt caching, eval statistics; (7) memory search (g), then cleanup tickets and the killing tests that only need landing (k31, k38–k42, k48, k58, k59, k61).
- **Next:** `/to-spec`, then `/to-tickets`, in the grilling session. Open question for `/to-spec`: one spec on one integration branch, or several specs (e.g. safety and Approval / Informer rework and evals / context, memory and cost).
- **Implementer models:** tickets are implemented in Cursor by Haiku or Composer 2.5. Haiku is much cheaper under a 100k-token context and much more expensive above it, so each ticket's `Model:` hint follows its expected context size: Haiku for small, contained tickets (≤ 2 source modules + 1 test file, landing or following an existing test); Composer 2.5 for anything that may exceed 100k; Composer 2.5 when unsure.

## H. Found while recording the ledgers (ticket 03, 2026-10-22, real administration, read-only)

| # | Issue | Where | Verified | Sev. | Fix |
|---|---|---|---|---|---|
| H1 | For balance-sheet ledgers, Informer's column balance ignores `period_from` (columns are year-to-date up to `period_to`); the `trial_balance` tool tells the model it returns "movements in the periods", so a quarter's VAT asked through it comes back as the year to date | `trial_balance` (Informer server) | real 2025 data: ledger 1500 "periods 4–6" = Q1 + Q2; ledger 8000 (P&L) honours the range | bug (wrong financial answer) | ticket 14 |

- **`vat_position` design (Q34):** ledgers chosen by number (1542 has no RGS code; configurable, defaults 8000 / 1500, 1542 / 1520, 1543 / closing target 1551); a quarter = year-to-date at its end minus year-to-date at the previous quarter's end; Q4 of a year already closed in Informer (the accountant books the closing inside Q4, moving the year to 1551) is refused with a message pointing to the accountant. VAT returns are quarterly (owner, 2026-10-22).
- **Upload probe result (ticket 02, 2026-10-22):** v1 rejects a file-only Purchase invoice (requires relation, dates, number, total, lines) and reports it with HTTP 200 plus an `error` body. ADR-012's upload premise is false; tickets 16, 17 and the upload parts of 19 are on hold pending a new design. Informer's documented route for "just hand over the file" is its **incoming e-mail address** (Settings → Incoming e-mail; Scan & Herken OCR reads the invoice; limits 20 MB per mail, 2 MB per attachment, 20 attachments), per Informer's helpdesk.
- **Upload redesign (Q36–Q37, 2026-10-22):** the upload stays an Informer feature behind the Informer MCP server (so the whole server stays replaceable by one Informer provides), as two plain tools: `check_purchase_invoice(path)` (read: refusal reason, or name, folder, size and any earlier upload date) and `upload_purchase_invoice(path, allow_duplicate=false)` (Write action, re-runs every check, refuses a repeat unless `allow_duplicate`). Chosen over a hidden pre-Approval check, which would be a private graph-to-server protocol a replacement server wouldn't offer and would fail quietly. The file goes through a hand-over transport set in the Informer server's settings: the Fixture world uses a recording fake; no real transport until a follow-up (likely the incoming e-mail address); with none configured neither tool is registered and nothing mentions uploads. PDF only (Q35 superseded), cap default 2 MB; upload log in the server. No v1 client or v1 fake. Ticket 10 (per-tool Approval description) is wontfix; tickets 13, 16, 17, 19, the spec and ADR-012 are amended.
