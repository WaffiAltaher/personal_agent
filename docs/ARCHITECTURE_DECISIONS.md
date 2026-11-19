# Architecture Decisions Log

Record of technical decisions made during the Personal Data Agent project. Each entry captures the context, options considered, decision made, and reasoning.

---

## ADR-001: LLM Provider — Gemini via langchain-google-genai
**Date:** on or before 2026-04-18 (the first commit already uses it)
**Status:** Accepted

**Context:** Need an LLM for the ReAct agent. Options: Claude API (via langchain-anthropic), Gemini (via langchain-google-genai), OpenAI (via langchain-openai), or a provider-abstraction layer (aisuite/LiteLLM).

**Decision:** Start with Gemini via langchain-google-genai. No abstraction layer. Introduce other models in the eval phase (Phase 7) for comparison.

**Reasoning:**
- [Fill in: why Gemini? cost? context window? free tier? tool-use quality?]
- Abstraction layers (aisuite/LiteLLM) add complexity without teaching agentic concepts
- LangChain's model interface already abstracts provider differences — swapping models later requires changing one import and one model string
- Multi-model comparison deferred to the eval phase where it serves a concrete purpose

**Consequences:**
- All Phases 0–6 tested against Gemini only
- Model-specific quirks in tool calling may not surface until Phase 7
- Easy to swap: change `ChatGoogleGenerativeAI` → `ChatAnthropic` when ready

---

## ADR-002: Vector Database — Chroma
**Date:** on or before 2026-04-18 (the first commit already uses it)
**Status:** Accepted

**Context:** Need a vector store for semantic memory (Phase 3). Options: Chroma (local, Python-native) or pgvector (PostgreSQL extension).

**Decision:** Chroma.

**Reasoning:**
- simplest approach for the goal of this project

**Consequences:**
- Semantic memory is a local Chroma collection on the owner's disk; no database server to run
- The collection uses cosine space since 2026-10 (review-findings ticket 24), which needed a one-off re-index
- [Fill in: anything else]

---

## ADR-003: Orchestration — LangGraph
**Date:** on or before 2026-04-18 (the first commit already uses it)
**Status:** Accepted

**Context:** Need an orchestration layer for the ReAct agent. Options: vanilla LangChain agents, LangGraph, CrewAI, AutoGen, raw Python.

**Decision:** LangGraph.

**Reasoning:**
- will force me to handle lower level of details - good for initial understanding, and later I will switch to a higher level of abstraction once I am confident with the details. 

**Consequences:**
- Approval (`interrupt()`), resumable runs (`SqliteSaver` checkpoints) and the per-tool retry policy are built on LangGraph features, so they are tied to it (ADR-010)
- [Fill in: anything else]

---

## ADR-004: Work/business data sources — ITtopia B.V., not PostNL
**Date:** 2026-06-07
**Status:** Accepted (supersedes the original Phase 5 "Confluence + JIRA" scope)

**Context:** The original plan extended the agent to PostNL work systems (Confluence + JIRA via Atlassian). Pointing a personal side-project agent at an employer's systems raises data-governance concerns — corporate data shouldn't flow through a personally-run agent, even when MCP scopes to my own permissions, and it likely violates PostNL policy.

**Decision:** Target **ITtopia B.V.** (a company I own) instead. Concrete sources: **Microsoft 365** (ittopia.nl email/calendar/contacts) and **Informer** (Dutch accounting system). Drop PostNL Confluence/JIRA entirely.

**Reasoning:**
- Clean consent and ownership — no infosec gatekeeper, I'm my own Azure AD admin.
- Richer, real daily workflows (invoicing, client comms, finance questions) that double as portfolio demos.
- Flagging the data-governance boundary unprompted is itself a credibility signal in interviews.

**Consequences:**
- Gmail + Google Calendar (Phase 2) are retired; the agent becomes ITtopia-only.
- New integration surface: MS365 and Informer (see ADR-005, ADR-006).
- Failure-handling and human-in-the-loop machinery from Phase 2 carries forward unchanged.
- Amended 2026-10-22: Gmail and Google Calendar are **not** retired. They stay bound as the owner's personal mail and calendar, next to ITtopia's MS365 and Informer; the owner uses both ("check both work and personal agendas"). Their Google login is checked at startup when they are bound (see the review-findings register, decision (j)).

---

## ADR-005: Microsoft 365 — consume a third-party MCP server (don't hand-build Graph tools)
**Date:** 2026-06-07
**Status:** Accepted

**Context:** Need ITtopia email/calendar/contacts in the agent. Options: (a) hand-build LangChain tools over Microsoft Graph (repeats Phase 2 OAuth/REST learning); (b) consume an existing MCP server.

**Decision:** Consume `@softeria/ms-365-mcp-server` (MIT, MSAL-based, Graph API). Run with a pinned version, the `outlook` preset, and `--read-only` to start.

**Reasoning:**
- Hand-rolling another REST client teaches nothing new; consuming an MCP server is a distinct, in-demand skill (the *consumer* side of MCP) — directly relevant to the "agentic AI engineer" target.
- The server is mature (active maintenance, CI, Dependabot, MIT, ~500★, frequent releases), uses Microsoft's own MSAL, supports presets, read-only mode, and least-privilege scope auditing.
- Data flow is local (stdio → Graph); no third-party cloud intermediary.

**Security hardening (required):**
- Use **my own Azure AD app registration** (own client ID + ITtopia tenant ID), not the built-in default app — I control consent and can revoke.
- Start `--read-only --preset outlook`; add `Mail.Send`/draft scopes only at the reminder-email workflow, gated by the existing human-in-the-loop interrupt.
- **Pin the version** (e.g. `@softeria/ms-365-mcp-server@<pinned>`); review release diffs before bumping; Docker image available for isolation if desired.
- Least-privilege Graph consent (Mail/Calendars/Contacts read first); audit with `--list-permissions`.
- Token cache in OS keychain (macOS Keychain via keytar), not file fallback.

**Consequences:**
- Dependency on a community npm package → supply-chain risk, mitigated by version pinning / Docker.
- Learn MCP client integration (capability discovery → tool binding via `langchain-mcp-adapters`).
- Failures now occur behind an MCP boundary — a different failure surface than in-process tools.

**Amendment (2026-10-07): Drafts, still no sending.**
- The agent may save Drafts: the Graph consent grows from mail-read to `Mail.ReadWrite` (a manual step in the Azure app registration; check it with `--list-permissions`). `Mail.Send` is still not granted, and nothing that sends is reachable.
- Pin bumped to `@softeria/ms-365-mcp-server@0.159.1`. `--read-only` and `--preset outlook` are replaced by `--enabled-tools` with an anchored pattern of exact names (`agent/tools/ms365_mcp.py`): the read tools `--read-only --preset outlook` exposes, plus exactly two Write actions, `create-draft-email` and `create-reply-draft`. The server derives the scopes it requests from the enabled tools, so it asks for `Mail.ReadWrite` but not `Mail.Send`.
- The loader enforces the same set by name (`McpServer.exposed_tools`), whatever annotations the server sets, and classifies the reads by name too (ADR-010). `download-bytes-to-file` is left out: it writes a local file although the server annotates it `readOnlyHint`.
- Both Draft tools go through the approval gate and are never retried by the agent; the server itself doesn't retry a failed POST except on 429.
- New optional setting `MS365_MCP_EXPECTED_USERNAME`, passed to the server, so it fails fast when the cached account isn't ITtopia's. The token cache stays in the macOS keychain (`MS365_MCP_USE_KEYTAR` is never set).

---

## ADR-006: Informer — author my own MCP server (the producer side)
**Date:** 2026-06-07
**Status:** Accepted

**Context:** Need ITtopia accounting data (Informer) in the agent. No MCP server exists for Informer; it exposes a REST API (API code + security code). Options: (a) wrap it as another LangChain tool; (b) author a standalone MCP server.

**Decision:** Author a minimal **Informer MCP server** (Python `mcp` / FastMCP), as its own phase (Phase 6), then consume it from the agent.

**Reasoning:**
- A plain LangChain tool duplicates Phase 2 learning — no new concept.
- Authoring a server teaches the *producer* side of MCP: server SDK, the three primitives (tools/resources/prompts), transport choice, auth at the protocol edge — none of which a `@tool` wrapper touches.
- Strongest single portfolio artifact: "consumed third-party MCP servers **and** authored my own over a system that had none." Closes the build-vs-buy question by demonstrating both sides in one project.

**Consequences:**
- More effort than a tool wrapper, justified by the learning and portfolio value.
- Produces a reusable, standards-based server (usable from Claude Desktop, Cursor, etc., not just this agent).
- Read tools first; write/booking tools deferred behind human-in-the-loop.

---

## ADR-007: Eval scope — RAGAS is not enough; add agent/trajectory eval
**Date:** 2026-06-07
**Status:** Accepted

**Context:** The plan said "Phase 7 = RAGAS + multi-model comparison." RAGAS evaluates **RAG (retrieval + generation)** quality — faithfulness, answer relevance, context precision/recall. It does **not** evaluate agent behaviour (tool selection, sequencing, failure recovery).

**Decision:** Split Phase 7 into (1) generation eval with RAGAS, (2) **agent/trajectory + tool-use eval** (LangSmith / DeepEval / custom LLM-as-judge), and (3) multi-model comparison across both.

**Reasoning:**
- The "agent" part of the project is exactly what RAGAS can't measure; omitting trajectory eval would leave the core competency unevaluated.
- Model comparison is only meaningful on a task suite hard enough to separate models — the multi-source ITtopia workflows provide that.

**Consequences:**
- More comprehensive (and more honest) evaluation story.
- Adds a second eval toolchain alongside RAGAS.

---

## ADR-008: Interface expansion (Streamlit/FastAPI) deferred and optional
**Date:** 2026-06-07
**Status:** Accepted

**Context:** Original Phase 6 was Interface Expansion (Streamlit → FastAPI). It sits ahead of evals in the original ordering.

**Decision:** Move evals ahead of interface work. Interface expansion becomes **optional Phase 8**, built only if time and usefulness warrant.

**Reasoning:**
- UI work is lower learning value for the agentic-engineering goal than evals.
- The CLI is sufficient for development and for tracing interview demos.

**Consequences:**
- Evals (high-value, portfolio-critical) are reached sooner.
- A polished UI may not exist for demos; Langfuse traces + CLI carry the demo instead.

---

## ADR-009: Model selection — `provider:model` via LangChain's `init_chat_model`; default Gemini 3.8 Flash
**Date:** 2026-10-07
**Status:** Accepted (refines ADR-001)

**Context:** The built-in default model was `gemini-2.0-flash`, which Google shut down on 2026-06-01; the configured `.env` model, `gemini-2.5-flash`, is near end of life too. Phase 7 compares Gemini with Claude (Sonnet 5.5), so switching provider must not need a code change. The graph built `ChatGoogleGenerativeAI` directly, so tests had to patch that class to fake the model. Options for multi-provider: (a) LangChain's provider-agnostic `init_chat_model`; (b) a routing layer such as aisuite or LiteLLM.

**Decision:** One `MODEL_NAME` setting in `provider:model` form (`google_genai:gemini-3.8-flash`, `anthropic:claude-sonnet-5-5`), built by `agent.chat_model.create_chat_model` through `init_chat_model`. Default `google_genai:gemini-3.8-flash`. `ANTHROPIC_API_KEY` is optional and required only when an Anthropic model is selected; a missing key stops the CLI with a clear message. `build_graph` takes an optional `model` and builds one from settings when it isn't given.

**Reasoning:**
- `init_chat_model` already maps a provider prefix to the right LangChain integration, and every integration is a `BaseChatModel` with `bind_tools`, so the graph doesn't care which provider it gets. A routing layer would add a second abstraction over the one LangChain already gives (ADR-001's reasoning still holds).
- Keys come from settings rather than the environment, so the factory can fail fast and name the missing setting instead of failing inside the provider SDK.
- A bare Gemini name (an existing `.env`'s `gemini-2.5-flash`) is mapped to `google_genai`: `init_chat_model` would otherwise infer Vertex AI for it.
- Injecting the model into `build_graph` gives tests and the eval harness one seam: a scripted fake model, with no patching of a provider class.

**Consequences:**
- Adds `langchain-anthropic` (which raised `langchain-core` to 1.6.x).
- Switching model is a `.env` change; the eval harness injects the model under test the same way.
- The module-level `agent_graph` is gone; callers use `build_graph(...)`.
- Learning lesson 0003 still patches `agent.graph.ChatGoogleGenerativeAI`, which no longer exists there.
- Amended 2026-10-25 (ADR-016): a third prefix, `claude_code:`, runs the chat model through the Claude Code CLI on the owner's subscription and needs no key. The built-in default becomes `claude_code:claude-sonnet-5-5`; `GOOGLE_API_KEY` stays required for embeddings.

---

## ADR-010: Write-action classification fails closed
**Date:** 2026-10-07
**Status:** Accepted

**Context:** Approval and the no-retry guard keyed off a hand-maintained set of tool names, `TOOLS_REQUIRING_APPROVAL`. MCP tools load with a server prefix (`ms365_…`), so none matched: dropping `--read-only` would have let MS365 writes skip approval and be retried on transient errors, possibly duplicating them (the known issue). A name list fails open: any tool nobody listed — a new local tool, a tool added by an MCP server upgrade, a renamed prefix — is treated as safe.

**Decision:** Every tool bound to the graph is classified as read or Write action when tools are loaded, and the class is stored in the tool's metadata (`agent/tools/classification.py`). Local tools declare it explicitly in `LOCAL_TOOLS` (`read_tool(...)` / `write_action(...)`). MCP tools go through `classify_mcp_tools(tools, read_allowlist=...)`, called once per server by the loader: a tool is read only if it is on that server's read allowlist (originally also when the server was trusted and the tool carried `readOnlyHint: true`; see the amendments). The graph treats a tool call as read only if its bound tool is classified read; everything else — Write actions, unclassified tools, unknown tool names — goes through the approval gate and is never retried automatically. MS365 is trusted for the annotation, because the pinned server derives `readOnlyHint` from the Graph HTTP method (GET).

**Reasoning:**
- Failing closed turns a classification mistake into an extra approval prompt instead of an unapproved, possibly duplicated write.
- Classification lives on the tool, so it travels with it through prefixes and renames; there is no second list to keep in sync.
- `readOnlyHint` is a hint a server sets about itself, so it counts only for servers we choose to trust (pinned, reviewed per ADR-005); the allowlist covers servers that don't annotate.
- One classification drives both approval and retry, so the two can't disagree.

**Consequences:**
- `TOOLS_REQUIRING_APPROVAL` is gone; adding a read tool means declaring it read, or it will ask for approval.
- Tests that bind ad-hoc tools must classify them (`read_tool`) or expect an approval pause.
- An MCP server upgrade that adds a tool without `readOnlyHint` makes it a gated Write action, not a silent read.
- Learning lessons 0003 and 0004 and the HITL reference still describe the old name set.
- Amended 2026-10-07 (ADR-005 amendment): MS365 reads are now classified by an explicit read allowlist, not by trusting `readOnlyHint`, because the bound tools are enumerated by name anyway and the real server annotates at least one local-file write (`download-bytes-to-file`) as read-only.
- Amended 2026-10-08: with no server trusted any more, the trust mechanism (`McpServer.trust_read_only_hint`) is removed, along with `McpServer.hidden_tools` (MS365's `exposed_tools` already leaves its account tools out). An MCP tool is read only by its server's read allowlist; `readOnlyHint` never classifies a tool.
- Amended 2026-10-22: an Approval covers only the Write actions in a batch, all or nothing. On reject, the reads proposed alongside them still run; only the Write actions get rejection messages (`status="error"`), and a rejected Write action can never reach the tools node. A new message on a thread paused for Approval counts as a reject: the pending Write actions are answered as rejected before the new message is processed, so the history never holds an unanswered tool call. Per-call approval was rejected as a feature with no demonstrated need, and one that every frontend would have to implement.

---

## ADR-011: The Fixture world is the only test and eval target
**Date:** 2026-10-07
**Status:** Accepted

**Context:** Tests and evals need MS365 mail, calendar and contacts, and an Informer administration. Informer has no sandbox: every API key reads and writes ITtopia's real books, and is limited to 60 requests per minute and 5000 per day. The real MS365 mailbox is the owner's working mailbox. Real data also changes, so runs on it aren't repeatable. Options: (a) mock the tools in Python; (b) run against real accounts; (c) seeded fakes behind the same interfaces the agent uses in production.

**Decision:** A Fixture world (`src/fixture_world/`) of seeded fakes is the only target for tests and evals; real services are touched only by the opt-in live smoke check. Seed data lives in versioned files under `fixture_world/data/`. MS365 is replaced at the MCP boundary by a stand-in MCP server (`fixture_world.ms365`) with the real server's tool names, parameters, annotations and response shapes; Informer is replaced at the HTTP boundary by a fake Informer API that the real Informer MCP server is pointed at. The agent loads the stand-ins through the same MCP loader, over stdio, under the same server names; the CLI's `--fixtures` flag selects them. Seeded dates move by whole weeks onto the current week (`fixture_world.clock`; pinned with `FIXTURE_WORLD_TODAY`), so "this week" finds the seeded meetings on any date.

**Reasoning:**
- Faking at the protocol boundary keeps the agent code under test identical to production: the MCP adapters, prefixes, classification, retry and fallback all run for real. A Python mock would skip exactly the boundary where failures happen (ADR-005).
- Faking Informer's HTTP API rather than its MCP server lets the server we authored be tested too (ADR-006).
- Seeded files make runs repeatable and free, need no credentials, and can never touch real mail or books.

**Consequences:**
- The stand-in must track the real server: a pin bump (ADR-005) means rechecking the stand-in's tool names and shapes. It emulates only what the agent uses (a subset of `$filter`, `$search` as a phrase match).
- Eval scores measure behaviour on seeded data; scenarios on real ITtopia data are a later step.
- Each MS365 tool call starts a fresh stand-in process (the adapters open a session per call), so any state the stand-in records across calls must live outside the process.
- Amended 2026-10-22: the Gmail and Google Calendar tools were left real in Fixture-world mode (only web search had a stand-in), so evals and `--fixtures` read the owner's real Google mail and calendar. They get seeded stand-ins with the same names and arguments, like the web search; the Fixture world then never needs a Google login.

---

## ADR-012: Informer has exactly two uses — financial questions and file-only purchase invoice upload
**Date:** 2026-10-22
**Status:** Accepted (narrows ADR-006's scope; the Informer MCP server itself stands)

**Context:** The Phases 5–7 build assumed Informer would drive collections: a `list_overdue_invoices` join tool, a `payment_reminder` MCP prompt, Payment reminder rules in system prompt v3, and a capstone eval of reminder Drafts to Clients. That is not how the owner uses Informer. The owner wants it for two things only: (1) questions about the financial situation, such as revenue and VAT to pay; (2) handing over a purchase invoice as just a file (PDF or image), which the accountant then books and tags. Informer's v2 API (the one our client uses) requires a relation, date, number, VAT option and lines to create a purchase invoice, so it can't take a file alone; v1's `POST /invoice/purchase/` marks no field as required and has a base64 `pdf` field. Neither version has a VAT-return endpoint.

**Decision:**
- Remove the overdue-invoice and payment-reminder capability entirely: the tool, the MCP prompt, the prompt rules (in a new prompt version, since released versions never change), the eval scenarios and the glossary terms.
- Keep the plain read tools and resources for financial questions, and add two read tools that do the arithmetic in code: `revenue` and `vat_position` (per quarter), over ledgers identified by their RGS codes in ITtopia's real chart of accounts. Other questions go through `trial_balance`; a question is promoted to a tool only when an eval shows the model getting it wrong.
- Add a file-only purchase invoice upload through **v1** `POST /invoice/purchase/`, as a Write action. It takes a local file path and reads the file itself, so the bytes never pass through the model. Its exact v1 behaviour (what a file-only record looks like to the accountant; whether images are accepted) is established by a manual probe before it is built. If images are rejected, they are converted to PDF locally.

**Reasoning:**
- Two uses and two only: a reminder workflow the owner doesn't want is cost, prompt length and test surface with no user.
- Money arithmetic in code is exact and testable; the same rule in the prompt can only be checked by an eval with a real model (Track B notebook 11's design drill).
- v1 is used for this one call because only v1 accepts a file without the bookkeeping details the accountant is meant to supply. Everything else stays on v2.
- A path, not file content, as the tool's input keeps large binaries out of the context and leaves room for later sources (an email attachment, a vendor's website) that only need to produce a local file.

**Consequences:**
- The Informer server is no longer read-only: its instructions and its read allowlist change, and the upload is gated by Approval and never retried (ADR-010).
- The client gains a v1 base URL next to v2; v1 is thinly documented, so the fake Informer models what the probe observed, not the spec.
- Eval scenarios are replaced: financial questions graded on exact amounts, uploads graded on the outcome the fake records, and a mixed batch.
- Track B findings that existed only because of the reminder work (k54, k55, M56, M57) are dropped.

**Amendment (2026-10-22, after the upload probe):** The premise that v1 accepts a file on its own is false. The probe (review-findings ticket 02) sent `POST /invoice/purchase/` with only the `pdf` field and got HTTP 200 with an `error` body naming relation, invoice date, expiry date, number, total and lines as required. v1 reports validation errors with HTTP 200, so any v1 call must treat an `error` body as a failure. The upload decision is replaced:
- The upload is two plain tools on the Informer MCP server: `check_purchase_invoice(path)`, a read that returns the refusal reason or the file name, size and the date of any earlier upload of the same contents; and `upload_purchase_invoice(path, allow_duplicate=false)`, a Write action that re-runs every check and refuses a repeat of earlier contents unless `allow_duplicate` is true. All Informer functionality stays behind the Informer server, so the whole server could be swapped for one Informer provides; neither the agent graph nor the Approval holds Informer-specific logic.
- The file reaches Informer through a hand-over transport chosen in the Informer server's settings. The Fixture world configures a recording fake; the real transport is a follow-up feature (most likely Informer's incoming e-mail address, where Scan & Herken reads the invoice; 2 MB per attachment). Until a transport is configured, neither tool is registered and nothing tells the model it can upload.
- PDF only, under a size cap (default 2 MB). The v1 client, the v1 base URL and the v1 fake endpoint are withdrawn; images and their conversion to PDF are dropped.
- Revenue and VAT ledgers are chosen by number, not by RGS code: one VAT ledger has none (ticket 03's ledger record).

Two plain tools were chosen over a hidden check that the Approval step calls before showing a Write action: that would be a private protocol between our graph and our server, which a replacement server would never offer, and it would fail quietly back to raw arguments. The cost is one extra model step, and an Approval that shows raw arguments; the server enforces every check at upload time either way.

---

## ADR-013: Shrink the model's view of the context, never the state
**Date:** 2026-10-22
**Status:** Accepted

**Context:** Above an 800k-token hard limit, `check_context_budget` trimmed whole turns and removed them from state with `RemoveMessage`. Track B notebook 05 showed it dropped the user's question first, could leave a tool result without its call, and removed every message when one tool result alone was over the limit, permanently. The pressure it was meant to relieve is not long conversations but large tool results within one turn. Options: (a) fix the trim (keep the question, drop call and result together, never drop everything); (b) summarise older rounds with a model call; (c) clear old tool results in the view sent to the model, leaving state untouched, and cap any single tool result.

**Decision:** (c). State and checkpoints keep every message. Before a model call whose context is over 100k tokens, tool results from earlier rounds are replaced in the view by a stub that says how big they were and that the tool can be called again, until the view is under 50k. User messages and every AIMessage stay, and every tool call keeps an answer. A single tool result over 20k tokens is truncated where the tool returns, with a marker. The count is the previous call's reported input tokens plus an estimate of the messages added since. The trim and its `RemoveMessage` path are deleted.

**Reasoning:**
- Clearing tool results targets the measured pressure; trimming turns targets one that doesn't occur at a 10-model-call step budget.
- A view can't corrupt the history: nothing is lost, so the result is reversible and always a valid message sequence by construction.
- Summarising adds a model call with its own failure modes, for runs this short.
- 100k is well under every candidate model's window and near where long-context quality and cost start to matter; clearing down to 50k stops it firing again on the next round.

**Consequences:**
- Clearing rewrites earlier messages, which invalidates a cached prompt prefix; it fires only above the threshold, never routinely.
- A cleared result is gone from the model's view for the rest of the run; the model must call the tool again if it needs it.
- The old trim's tests and Track B's killing tests for it (k23, k25, k90) are replaced by tests of the new guarantees: the question is kept, no tool call is left unanswered, the view is never empty.

---

## ADR-014: Long-term memory is written only on an approved request
**Date:** 2026-10-22
**Status:** Accepted

**Context:** After every run, `log_run_to_memory` embedded the final answer into semantic memory, right or wrong. A wrong answer was later retrieved as context and could reinforce itself; text from an email or web page that reached an answer was stored and later returned as if it were trusted context (stored prompt injection). Every interaction was also sent to the embeddings API.

**Decision:** Semantic memory is written only through a `remember` tool, classified as a Write action, so the owner approves each memory. Answers are never ingested automatically, and the interactions collection is dropped. The episodic store stays local as a run log (question, tools used, run totals of usage and cost, outcome). The semantic collection uses cosine distance, with a threshold calibrated on a labelled Fixture-world set.

**Reasoning:**
- A memory changes the agent's future behaviour, so it is a write and fails closed like one (ADR-010).
- Removing automatic ingestion closes both the feedback loop and the injection path at the source, instead of labelling retrieved memories as untrusted and hoping the model honours it.
- Far less personal and client data is sent to the embeddings API.

**Consequences:**
- The agent remembers less on its own: anything worth keeping must be asked for and approved.
- Existing stores need a one-off re-index into the cosine collection.
- Plaintext run logs on the local disk are accepted.

---

## ADR-015: Outlook attachment saves go through an agent-side wrapper that confines the server's local-file write
**Date:** 2026-10-25
**Status:** Accepted

**Context:** The owner wants the agent to save email attachments from Outlook and Gmail into its own folder, `~/Downloads/personal_agent`, with each mailbox writing only into its own subfolder. For Outlook, the pinned `@softeria/ms-365-mcp-server` already offers `download-bytes-to-file`. It writes Graph bytes to **any absolute path** the caller gives it, refuses an existing file, and is annotated `readOnlyHint` although it writes to disk, which is why it was kept out of the agent's tools. The Approval prompt shows a Write action's raw arguments (ADR-012). For the server's tool, those would be a Graph path and an output path, with nothing showing which attachment is being saved.

**Decision:** The model never sees `download-bytes-to-file`. The agent exposes its own Write action, `ms365_save_attachment(message_id, attachment_id, file_name, include_inline=false)`. It looks the attachment up with `list-mail-attachments` and refuses unless `file_name` matches the real name. It then chooses the path itself, inside `outlook/`, and calls the server's tool with a temporary name, then applies the shared save rules (no overwrite, skip identical copies, `(1)`/`(2)` on a clash, 25 MB cap). The Gmail save follows the same contract and rules.

**Reasoning:**
- **Exposing the server's tool as a Write action guarded only by Approval** would leave the destination to the model and to the owner's reading of a path in every prompt.
- **A Microsoft login of our own** for downloading would go against ADR-005: the server owns the Graph login.
- **A required `file_name` argument** puts the real attachment name into the generic Approval prompt, without adding mailbox logic to the graph (ADR-012's reason for avoiding a private protocol between graph and server). The wrapper checks the name again at save time rather than trusting what Approval showed.

**Consequences:**
- The MS365 server's enabled tools now include `download-bytes-to-file`, and the loader must keep it unbound by name. A test pins this.
- The save costs one extra Graph call (the attachment lookup) and a rename on disk.
- If the server changes `download-bytes-to-file`'s contract, the wrapper is the one place to fix. Review it when bumping the pin.

---

## ADR-016: Chat model through the Claude Code CLI on the owner's subscription
**Date:** 2026-10-25
**Status:** Accepted (amends ADR-009)

**Context:** Every model the agent can use is billed per token through an API key, on top of the owner's Claude subscription. The Google project's prepaid credit is depleted (chat and embeddings both return `402 RESOURCE_EXHAUSTED`). The agent only ever runs on the owner's laptop, where Claude Code (`claude`, logged in to a claude.ai Pro subscription) and Cursor (`cursor-agent`) are installed. Both CLIs are agents in their own right: they run their own tool loop and return a final answer, never tool calls for a caller to run. The graph depends on `bind_tools` and structured `tool_calls`, so that the Approval step, the retry policy, checkpoints and trajectory evals see every tool call. Options: (a) the CLI as the model only, behind a `BaseChatModel`; (b) the CLI as the agent, with the agent's tools exposed to it as an MCP server.

**Decision:** (a). `MODEL_NAME=claude_code:<model>` builds a chat model that makes each turn one stateless call: `claude -p --safe-mode --strict-mcp-config --disable-slash-commands --no-chrome --tools "" --no-session-persistence --output-format json --model <model>`, from a neutral working directory, with `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN` and `ANTHROPIC_BASE_URL` removed from its environment. The system prompt goes in `--system-prompt`. The model view and the bound tools' schemas go on stdin as a JSON array of messages. The prompt asks for a JSON reply, either an answer or tool calls, and the wrapper validates it against the bound tools and re-asks once on an invalid reply. Real-mode startup requires `claude auth status` to report a claude.ai login. Claude Code comes first; Cursor waits for a spike.

**Reasoning:**
- **The CLI as the agent** would hand tool execution to Claude Code: Write actions would depend on its permission prompts instead of ADR-010, and checkpoints and trajectory evals would see nothing.
- **`--safe-mode` and the other isolation flags:** `--system-prompt` and `--tools ""` alone still loaded the owner's global CLAUDE.md, auto-memory, skills and plugins: about 55k tokens per call, which also let personal instructions steer the agent. With the flags, the same call was about 1k tokens. `--bare` also isolates, but never reads OAuth, so it can't use a subscription.
- **Removing the API-key variables:** Claude Code bills an API key when one is in its environment. Today none reaches the child (pydantic-settings doesn't export `.env`), but only by luck.
- **The prompt plus wrapper validation, not `--json-schema`:** Claude Code enforces a schema by giving the model a tool. In a test, Haiku then tried to call the agent's tool natively, was refused, and answered "I couldn't get the weather": a believable wrong answer. With no tools in sight, Haiku returned valid tool calls. A failure of the prompt route is a parse error the wrapper catches. Cursor has no schema flag either.
- **Stateless calls, not `--resume`:** LangGraph stays the only record of the conversation, ADR-013's model view keeps working, and a checkpoint resumed days later needs no CLI session.
- **JSON messages, not a plain transcript:** a tool result (an email body) can't forge a new user turn when every content is a JSON-escaped string. That keeps the boundary the API's message slots gave.
- **Cursor deferred:** `cursor-agent -p` cannot turn its tools off (the closest is `--mode ask`, sandbox and an empty workspace), so injected text could make it read files. It also has no system-prompt or schema flag.

**Consequences:**
- The owner's subscription limits now bound agent and eval runs. Hitting the usage limit stops the run with the reset time; there is no fallback to an API key and no waiting. Timeouts (180 s, `CLAUDE_CODE_TIMEOUT_S`), CLI crashes and a reply still invalid after the re-ask also stop the run, with the checkpoint kept. None of these is retried. After a stop the owner can continue the Conversation with `python -m agent.cli --resume <id>` (a bare `--resume` takes the most recent): the checkpoint is LangGraph's, so this needs no Claude Code session. (Amended: this was "a later idea" when the ADR was written; the interactive CLI added it.)
- Cost is the API-equivalent price from `pricing.py`, looked up with the model the CLI reports (so `sonnet` and `claude-sonnet-5-5` price the same). A model without a table row shows no cost.
- Effort stays at Claude Code's default. There is no setting until evals show it matters.
- Tests drive a stand-in `claude` executable at the subprocess boundary (ADR-011), selected with `CLAUDE_CODE_BINARY`. One `live` test calls the real CLI and guards the isolated context size, since a Claude Code update could start loading the owner's setup again.
- The wrapper depends on Claude Code's CLI flags and its `--output-format json` shape. Recheck them when Claude Code updates.
- Embeddings still need `GOOGLE_API_KEY`: neither CLI offers them.
- Amended 2026-10-25 (ticket 09): a reply that is exactly one JSON object inside one Markdown code fence (```json or ```) is accepted like an unfenced one, because Sonnet fenced most replies and each re-ask doubled the turn's cost; anything else around the object (a stray tag, prose) is still invalid and re-asked.
- Amended 2026-10-25 (owner's second real run): text before the contract object is ignored too. Sonnet often narrated its step or wrote the call out as markup before the JSON, and each such reply was re-asked. The reply must still end in the object (fenced or not); text after it, or no object, is re-asked. The calls are validated against the bound tools and Write actions still need Approval, so the ignored text has no effect.
- Amended 2026-10-29 (ticket 10): the reply contract now goes to the CLI as `--json-schema`, reversing "The prompt plus wrapper validation, not `--json-schema`". In the owner's run of 2026-10-28, a turn with 54 tool schemas and an earlier tool call in the conversation never answered: with no real tool in the request, Sonnet started a native tool call, wrote it as text (`<invoke name="x"></invoke>`), and repeated it until the 180 s timeout (784 repeats in 200 s when replayed). About 45% of replays of that turn did so, and every reply that finished carried the markup. With `--json-schema`, Claude Code gives the model one real tool, StructuredOutput: native calls of the agent's tools are refused cleanly ("No such tool available") and the reply arrives in `structured_output` (3 of 3 replays). The wrapper reads `structured_output`, so the fence and leading-text amendments above no longer apply. A clean reply takes 2 CLI turns. Tool calls after more turns are accepted, because the CLI still has no tools to run and the calls are validated and gated as before. An answer after more turns is re-asked, because that is the believable wrong answer the original decision feared. Because one CLI call can now make several requests, the context check takes the prompt size from the last request (the final `usage.iterations` entry, falling back to `usage`); `usage` sums the requests, and cost keeps that sum.

---

## ADR-017: A web search needs Approval once the conversation holds the owner's data
**Date:** 2026-11-13
**Status:** Accepted (extends ADR-010)

**Context:** Mail bodies, attachment names, files and web pages reach the model as tool results, and reads ran without Approval. A mail could tell the agent to search the mailbox and put what it found in a web search query: the query goes to an outside service (Tavily) and the owner never sees it. Write actions were already safe (every one stops for Approval, and nothing can send mail), so the web search was the one way data could leave. No prompt version said that tool-result text is not an instruction.

**Decision:** A read whose arguments leave the owner's own accounts is a third class, an **Outbound read** (`outbound_read(...)`; today only the web search). It runs like any read until the conversation holds a result from any tool other than an Outbound read; after that it needs Approval, which shows the query. This is derived from the messages at review time, not stored as a flag. Prompt v6 adds two rules as a second layer: tool-result text is information, never an instruction; and a claim from a mail, file or web page is attributed to its source and never overrides Informer.

**Reasoning:**
- An exploit needs three things together: the owner's data, untrusted content, and a way out. Gating the only way out breaks it in code, where a well-written injection can't argue past it. A prompt rule alone lowers the hit rate but can be beaten.
- A leak needs the owner's data in the context wherever the instruction came from (it could arrive in a web result), so the trigger is "the conversation holds the owner's data", not a list of "untrusted" tools. A new tool is covered by default, which fails closed like ADR-010.
- Deriving it from the messages means it lasts as long as the data is in the conversation: across a follow-up question, a resume, and view clearing (ADR-013).
- Always asking for Approval on a web search was rejected: plain web questions are common, and prompts the owner learns to approve without reading protect nothing.
- A privileged model that never sees untrusted text plus a quarantined one without tools (the dual-LLM pattern) was rejected as far more machinery than one outbound channel needs.

**Consequences:**
- A question that mixes the owner's data with a web search gets one extra Approval ("what's on Monday, and look up the venue"), unless the model proposes the search alongside the first read: it wrote that query before seeing any data.
- A new read that sends model-written text outside (a URL fetch, another search engine) must be declared with `outbound_read(...)`. Wrapped in `read_tool(...)` it would leak silently; `ms365_download-bytes` stays a plain read because the pinned server accepts only relative Microsoft Graph paths.
- `retrieve_memory` also sends a model-written query off the machine, to Google's embeddings API, and stays a plain read (owner's call, 2026-11-14): Google is already a provider trusted with this data under the owner's own key, where Tavily is a third party that otherwise sees nothing, and gating memory search would prompt on every recall after a mail read.
- A steered answer (a mail falsely claiming an invoice is paid) is not stopped by any gate. Only the v6 rules address it, and the `injection-mail-false-claim` eval scenario measures how well.
- The eval suite separates the guarantee from the rate: `leaks` must be zero (code enforces it), while `leak_attempt_rate` is model behaviour and is what a prompt change is judged on.

---

<!-- Template for new decisions:

## ADR-XXX: [Title]
**Date:**
**Status:** Proposed | Accepted | Deprecated | Superseded by ADR-XXX

**Context:** What is the issue? What forces are at play?

**Decision:** What was decided.

**Reasoning:** Why this option over alternatives.

**Consequences:** What follows from the decision. Both positive and negative.
-->
