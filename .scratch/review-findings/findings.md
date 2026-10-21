# Review findings register (Track B, concepts 1–8)

Findings from the Track B notebooks (concepts 1–5, `notebooks/01`–`04`) and Lesson 7's experiments (concepts 6–8, `notebooks/05`, Part A). This is a register, not tickets yet: each item becomes a ticket under this folder once its design question (if any) is decided.

Every item is verified by running code unless marked *read-only*. Severity: **bug** = user-visible · **latent** = will bite under a reachable condition · **cosmetic**. Fix: **mech** = mechanical · **decision** = needs the owner's call (grouped at the end).

Noise fixes: fix the cause when the message points at something we control; route it to a log file when it's legitimate log output in the wrong place. Never raise a log level or add a warning filter just to silence output.

Do the notebooks' Part C drills **before** any of the test gaps below are closed. Adding a killing test to `tests/` turns its drill's answer from "survived" into "caught", so the drill teaches nothing after that.

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
