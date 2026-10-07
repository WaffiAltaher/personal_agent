# Spec: Complete Phases 5–7 (MS365 MCP, Informer MCP server, evals)

Status: ready-for-agent

Vocabulary: business terms follow `GLOSSARY.md` (Client, Overdue invoice, Draft, Payment reminder, Write action, Fixture world). Agent-engineering terms follow `learning/GLOSSARY.md`. Decisions respect `docs/ARCHITECTURE_DECISIONS.md` (ADR-004 to ADR-008).

## Problem Statement

The ITtopia personal data agent is half built. It can read files, search the web, remember past runs and pause for approval. But it still points at personal Gmail and Google Calendar, which ADR-004 retired. It reads the ITtopia Outlook mailbox only in read-only mode, and cannot draft anything there. It knows nothing about ITtopia's accounting in Informer. Nobody has measured whether it picks the right tools or answers faithfully.

Its configured model is `gemini-2.5-flash`, and its built-in default is `gemini-2.0-flash`, which Google has already shut down. Both are near or past end of life. Memory search is literal keyword matching, so natural phrasings miss runs that are relevant.

The owner wants to run ITtopia with this agent every day: triage the inbox, chase overdue invoices, answer finance questions. They also want to use it as a portfolio piece and a learning vehicle for agentic engineering. For that, every decision has to be recorded so they can study it and explain it in an interview.

## Solution

Finish the agent so it runs the four ITtopia workflows in the master plan. Microsoft 365 and Informer are the business data sources. Gmail and Google Calendar remain available but are not used for ITtopia work:

1. **Inbox triage:** summarise mail on a topic and propose Drafts as replies.
2. **Overdue-invoice reminders (the capstone):** find Overdue invoices in Informer and draft one Payment reminder per Client in Outlook.
3. **Finance questions:** answer "what is outstanding?" and trial-balance questions from Informer.
4. **Research:** search the web and summarise.

The agent reaches Microsoft 365 through the third-party MCP server it already uses. It may create Drafts there, but never send. It reaches Informer through a new MCP server the owner authored, which is read-only. Every Write action pauses for the owner's approval, and none is ever retried automatically. A seeded Fixture world stands in for the real mailbox, calendar and Informer administration. Every test and eval runs against it, so the whole build completes without touching real data.

An eval harness scores the agent on two levels:
- **Trajectory:** did it pick the right tools, in the right order, and recover from failures?
- **Generation (RAGAS):** were its answers faithful and relevant?

It compares Gemini 3.8 Flash with Claude Sonnet 5.5 on quality, cost and latency.

Learning materials (notebooks, checkpoint answers) are written by the owner after the build, not by this spec.

## User Stories

### Model and dependencies

1. As the owner, I want the agent to default to a supported Gemini model (`gemini-3.8-flash`), so that it keeps working after older Flash models are shut down.
2. As the owner, I want to pick the agent's model with a single `provider:model` setting, so that I can switch between Gemini and Claude without code changes.
3. As the owner, I want the agent to refuse to start with a clear message when the chosen model's API key is missing, so that I don't get an obscure stack trace.
4. As the owner, I want the MS365 MCP server pinned to a current exact version, so that upgrades are deliberate and reviewed (ADR-005).
5. As a maintainer, I want the Python MCP SDK held on the 1.x line, so that it stays compatible with `langchain-mcp-adapters`.

### Google sources (kept)

6. As the owner, I want Gmail's draft tool treated as a Write action like any other, so that approval covers it too.
7. As the owner, I want the agent to use MS365, not Gmail, for ITtopia work, so that ITtopia business stays in the ITtopia mailbox.
8. *(Retiring Gmail and Google Calendar is out of scope.)*

### Microsoft 365 via MCP (Phase 5)

9. As the owner, I want to ask "what meetings do I have this week and who is attending?" and have the agent combine calendar, contacts and mail, so that I get one coherent answer.
10. As the owner, I want to ask the agent to summarise unread mail about a topic, so that I can triage the inbox quickly.
11. As the owner, I want the agent to propose a reply as a Draft in my Outlook mailbox, so that I can review and send it myself.
12. As the owner, I want the agent to have no way to send mail, delete mail, move mail, or change calendar events, so that the worst a mistake can produce is an unwanted Draft.
13. As the owner, I want every Draft creation to pause for my approval with a readable summary of recipient, subject and body, so that nothing appears in my mailbox without my consent.
14. As the owner, I want a rejected Draft to be acknowledged by the agent and never silently retried, so that "no" means no.
15. As the owner, I want any tool the agent can't classify as read-only to be treated as a Write action, so that a future server upgrade can't slip in an unapproved write.
16. As the owner, I want the agent to start with its local tools and a clear notice when the MS365 server fails to start, so that one broken integration doesn't block everything else.
17. As the owner, I want an expired or missing MS365 login to show up as a clear message telling me to run the login command, so that I know how to fix it.
18. As the owner, I want the agent to fail fast when the cached MS365 account isn't the expected ITtopia account, so that it never reads the wrong mailbox.
19. As the owner, I want transient MS365 errors (timeouts, 429, 5xx) retried with backoff on read tools only, so that blips don't derail a run.
20. As the owner, I want an error a tool reports through MCP to reach the model as a ToolMessage, so that the agent can explain or work around it.
21. As the owner, I want the MS365 login and account-management tools hidden from the model, so that it can't log me out or switch accounts.
22. As the learner, I want MCP tool calls to appear as clearly named spans in Langfuse, so that I can show the client handshake and the tool calls in a trace.

### Memory query rewriting

23. As the owner, I want memory search to turn my natural-language request into good search queries before searching, so that "what did I ask about invoices last week" finds runs that mention "Informer" or "overdue".
24. As the owner, I want the rewritten search to cover both episodic run history and semantic memory, so that both kinds of recall improve.
25. As the owner, I want memory search to fall back to my literal query when the rewriting step fails, so that a rewriting error never makes memory search fail.
26. As a maintainer, I want the rewriting model to be configurable separately, and to default to the agent's model, so that it can later move to a cheaper model.

### Informer MCP server (Phase 6)

27. As the owner, I want an MCP server for Informer that I authored, so that any MCP client (this agent, Claude Desktop, an IDE) can read ITtopia's accounting.
28. As the owner, I want to list and search Relations, so that the agent can find a Client and their email address.
29. As the owner, I want to list Sales invoices filtered by status and by Relation, so that the agent can see a Client's invoice history.
30. As the owner, I want a dedicated "overdue invoices" tool. It returns Overdue invoices as of a given date (default today), grouped by Client, with each Client's total Open amount, so that the model doesn't have to do date maths over pages of raw invoices.
31. As the owner, I want a trial-balance tool for a year and a range of periods, so that I can ask finance questions about the ledgers.
32. As the owner, I want the chart of accounts and the administration details exposed as MCP resources, so that I can learn when a resource fits better than a tool.
33. As the owner, I want a "payment reminder" MCP prompt template, so that I can learn the third MCP primitive and the agent writes reminders in a consistent tone.
34. As the owner, I want the server to page through Informer results itself, up to a sensible cap, so that the model never sees half a list without knowing it.
35. As the owner, I want the server to stay under Informer's limits (60 requests per minute, 5000 per day), so that ITtopia's API key is never blocked.
36. As the owner, I want rejected Informer credentials reported as a clear tool error naming the setting to check, so that I can fix misconfiguration quickly.
37. As the owner, I want amounts returned as exact decimal strings in EUR and dates in ISO format, so that the model never sees floating-point artefacts.
38. As the owner, I want the server to expose no write tools at all, so that the agent cannot change my books (ADR-006: writes are deferred).
39. As the owner, I want the agent to load Informer tools the same way it loads MS365 tools, with a clear prefix, so that both MCP integrations behave alike.
40. As the owner, I want the agent to start without Informer tools, with a notice, when Informer credentials aren't configured, so that the rest of the agent still works.

### Cross-domain capstone

41. As the owner, I want to ask "which clients are overdue on payment, and draft reminder emails" and get one Payment reminder Draft per Client, listing each Overdue invoice with number, due date and Open amount, so that chasing payments takes minutes.
42. As the owner, I want the agent to ask for approval before creating each batch of Drafts, so that I can catch a wrong recipient or a wrong amount.
43. As the owner, I want Clients without an email address in Informer reported to me instead of guessed, so that a reminder never goes to the wrong person.
44. As the owner, I want the whole capstone run visible as a single Langfuse trace spanning Informer and MS365, so that I can demo it in an interview.

### Fixture world

45. As a maintainer, I want a seeded Fixture world containing a fake mailbox, a fake calendar and a fake Informer administration, so that tests and evals are repeatable, free and never touch real data.
46. As the owner, I want to run the CLI against the Fixture world with a single flag, so that I can demo the agent safely.
47. As a maintainer, I want the fake Informer API to support pagination, rate-limit headers and switchable failures (401, limit exhausted, 5xx), so that the server's handling of each is testable.
48. As a maintainer, I want the stand-in MS365 server to use the real server's tool names and response shapes for the tools we use, so that the same agent code runs against both.

### Evals and model comparison (Phase 7)

49. As the learner, I want a versioned dataset of 10–20 scenarios over the Fixture world, covering the four workflows plus failure-recovery and rejection cases, so that evals reflect real ITtopia work.
50. As the learner, I want each scenario to declare:
    - the required tools
    - any ordering constraints
    - the forbidden tools
    - the expected facts in the answer
    - whether its approval prompts are auto-approved or auto-rejected

    so that both trajectory and outcome can be scored.
51. As the learner, I want trajectory metrics to cover:
    - tool-selection precision and recall
    - whether ordering constraints were satisfied
    - violations of the forbidden-tool list
    - recovery after an injected tool failure

    so that I can measure agent behaviour (ADR-007).
52. As the learner, I want RAGAS metrics (faithfulness, answer relevancy, context precision and recall), using tool outputs as the retrieved contexts, so that I can measure answer quality.
53. As the learner, I want a judge model that is configured separately from the model under test, so that a model never grades itself.
54. As the learner, I want token counts, cost and latency recorded for every scenario run, so that the comparison covers efficiency as well as quality.
55. As the learner, I want every eval run tagged in Langfuse with the model, prompt version, scenario and eval-run identifiers, so that I can drill from a score into the trace.
56. As the learner, I want to run the suite with one command for a chosen model and number of repeats, so that the comparison accounts for run-to-run variation.
57. As the learner, I want a markdown comparison report (Gemini 3.8 Flash vs Claude Sonnet 5.5) generated from the results, so that I can justify a model choice with data.
58. As the learner, I want the raw results saved as JSON next to the report, so that I can re-analyse them later.

### Docs

59. As the owner, I want each new architectural decision appended to the ADR log by the ticket that makes it, so that the "why" is recorded next to the change.
60. *(Learning notebooks and checkpoint answers are out of scope; the owner writes them.)*
61. *(Master plan and CLAUDE.md updates are out of scope; the owner makes them.)*
62. As the owner, I want a read-only live smoke check I can run after setting up credentials, so that I can confirm the real MS365 and Informer connections work.
63. As the owner, I want a single interactive setup wizard that walks me through every manual step, so that preparing keys and logins is one sitting.

## Implementation Decisions

### Model selection
- The model is chosen by a `provider:model` setting (for example `google_genai:gemini-3.8-flash` or `anthropic:claude-sonnet-5-5`), built through LangChain's provider-agnostic chat-model factory. No aisuite or other routing layer.
- The default is `gemini-3.8-flash`.
- An Anthropic API key is optional in settings, and required only when an Anthropic model is selected.
- **Graph seam:** `build_graph` takes an optional chat model as a parameter (alongside the existing checkpointer and tools parameters), and creates one from settings when it isn't given. Tests and the eval harness inject the model instead of patching the Gemini class.

### Write-action classification (fail closed)
- Every tool bound to the graph is classified as read or Write action when tools are loaded.
- Local tools declare their class explicitly.
- MCP tools are read only if they are on an explicit read allowlist, or carry the MCP read-only annotation from a server we trust. Anything unclassified is a Write action.
- Write actions always go through the approval gate and are never retried automatically.
- This replaces the hand-maintained set of tool names that require approval, so the tool-name prefix can no longer desynchronise approval, which is the known issue in `docs/known_issues.md`.
- A test asserts that every tool bound to the graph is either read-classified or gated.

### MS365 integration
- Pin `@softeria/ms-365-mcp-server` to an exact current version (0.159.1 when researched) with the `outlook` preset.
- Drop `--read-only`. The agent's tool set is restricted to the read tools `--read-only` would expose, plus exactly two Write actions, `create-draft-email` and `create-reply-draft`. Every other write tool (send, delete, move, update, calendar changes, rules, folders, permissions) must be unreachable by the model.
  - The implementer chooses the mechanism (a server flag for enabled tools, or a client-side filter), but a test must assert the exact set of bound tool names against the Fixture world stand-in.
- Login and account-management tools stay hidden.
- New optional setting: the expected MS365 username, passed to the server so it fails fast when the cached account doesn't match.
- The token cache stays in the macOS keychain (ADR-005). Do not disable keytar.
- Graph permission scope grows from mail-read to `Mail.ReadWrite`. This is a manual step, and ADR-005 is amended to record it.

### Loading MCP tools at the boundary
- One loader starts all configured MCP servers (MS365, Informer) through `langchain-mcp-adapters`, with server-name prefixes.
- Each server is optional and isolated. If one fails to start, or its credentials aren't configured, the agent starts with the rest and tells the user which integration is unavailable and why.
- At the start of a run, an MS365 authentication failure is turned into an actionable message naming the login command.
- MCP tool errors and server crashes in the middle of a run reach the model as error ToolMessages through the existing fallback.
- The existing retry policy applies at the MCP boundary unchanged: transient errors only, read tools only.

### Memory query rewriting
- Both memory retrieval tools take the user's natural-language request. A rewriting model call produces a semantic query for Chroma and a short list of keyword variants for the SQLite episodic search. Results are merged, deduplicated and ranked.
- Rewriting failure falls back to the literal query.
- The rewriting model is a separate setting that defaults to the agent's model.

### Informer MCP server
- A separate, independently runnable package in this repo. It is a stdio MCP server built with the Python MCP SDK 1.x (FastMCP), and is usable by any MCP client.
- Configuration: API key, security code, and a base-URL override, which is how the Fixture world points it at the fake API.
- Auth uses the `Apikey` and `Securitycode` headers against Informer API v2.
- **Tools (read-only):**
  - list/search Relations
  - get Relation
  - list Sales invoices by filter and Relation
  - get Sales invoice
  - list Overdue invoices as of a date, grouped by Client with totals
  - trial balance for a year and period range
- **Overdue invoice is computed** by the server, because Informer has no such filter: an open Sales invoice with Open amount > 0 and a due date before the as-of date. This matches `GLOSSARY.md`.
- **Client:** a Relation that has at least one Sales invoice. The API cannot tell customers from suppliers.
- **Resources:** the administration details and the chart of accounts (ledgers).
- **Prompt:** a Payment reminder template parameterised by Client and invoices.
- **Pagination** is handled inside the server, with a page cap. A truncated result says it is truncated.
- **Rate limiting:**
  - A client-side limiter keeps the server at or under 60 requests per minute.
  - The server reads the remaining-quota headers.
  - An exhausted daily quota produces a clear tool error.
- **Errors:**
  - Rejected credentials produce a tool error naming the settings to check.
  - Transient upstream failures are raised in a form the agent's retry policy recognises as transient.
- **Data format:** money as decimal strings in EUR, dates as ISO strings.
- No write endpoints are exposed.

### System prompt
- A new prompt version, built on the current prompt versioning, adds:
  - ITtopia context
  - the glossary rules: Drafts only, never send; one Payment reminder per Client; report Clients without an email address
  - guidance for combining data from Informer and MS365
- Langfuse tags the prompt version as it does today.

### Fixture world
- Seeded data (a mailbox, calendar events, contacts, Relations and Sales invoices including Overdue invoices) lives in versioned fixture files.
- **Stand-in MS365:** a small local MCP server that reproduces the real server's tool names and response shapes for the tools the agent uses, including the two draft tools. Created Drafts are recorded so tests can inspect them.
- **Fake Informer:** a small local HTTP fake of Informer API v2, covering only the endpoints the server uses, with pagination, rate-limit headers and switchable failure modes.
- The Informer MCP server runs against the fake through the base-URL override.
- A single CLI flag, and the eval harness, run the whole agent against the Fixture world.

### Eval harness
- Runnable as a module command that takes the model, the judge model, the number of repeats and a scenario filter.
- Scenarios live in a versioned dataset file, and each declares:
  - the input
  - the approval policy (approve or reject)
  - any failure to inject
  - the required tools
  - any ordering constraints
  - the forbidden tools
  - the expected answer facts
- The harness scores trajectory metrics itself, and generation metrics with RAGAS, using tool outputs as contexts.
- It records tokens, cost and latency from model usage metadata.
- It tags Langfuse traces with the model, prompt version, scenario and eval-run identifiers.
- It writes a results JSON file and a markdown comparison report.
- The Claude model under comparison is Claude Sonnet 5.5 (`claude-sonnet-5-5`).

### Google sources
- Gmail and Google Calendar tools stay.
- Under the fail-closed classification, Gmail's draft tool is a Write action, and its read tools and the Calendar read tools are read.
- The new system prompt tells the agent to use MS365 for ITtopia work.

### Docs
- New ADRs are appended to the ADR log by the ticket that makes each decision:
  - the fail-closed Write-action classification
  - the Fixture world
  - the model change
  - the `Mail.ReadWrite` scope amendment
- Notebooks, checkpoint answers, master plan and CLAUDE.md updates are left to the owner.

### Manual setup and live check
- The owner's one manual ticket is an interactive setup wizard, generated with the `/wizard` skill and run by the owner, that walks through every manual step:
  - creating the Informer API key and finding the security code
  - getting an Anthropic API key
  - granting the Azure app `Mail.ReadWrite` and checking it with `--list-permissions`
  - the one-time MS365 login
  - setting the expected username
  - starting local Langfuse
  - filling in `.env`
- A read-only live smoke check verifies MS365 and Informer connectivity against real services. It never creates a Draft.

## Testing Decisions

- **What makes a good test:** it exercises behaviour through a public seam and asserts on observable outcomes: the messages the model sees, tools invoked or skipped, interrupts raised, Drafts recorded in the Fixture world, MCP tool results. It does not assert on private helpers or internal call order.
- **Seam A, the graph (the primary seam).** `build_graph` with an injected scripted fake chat model, injected tools, and an in-memory checkpointer. It covers:
  - approval for MS365 Drafts, and the absence of retries for Write actions
  - fail-closed classification of unknown tools
  - rejection handling
  - memory query rewriting, including the fallback
  - MCP boundary failures: server down at start, auth expired, a tool error reported through MCP, a crash in the middle of a run
  - the capstone flow end to end against the Fixture world
  - Existing graph and retry tests move from patching the Gemini class to injecting the model.
- **Seam B, the Informer MCP server.** Exercised over the MCP protocol through a real in-process or stdio client session against the fake Informer API. It covers:
  - tool, resource and prompt discovery
  - the Overdue invoice calculation, including the boundaries: due today, open amount zero, partially paid
  - pagination and the truncation notice
  - rate-limit behaviour
  - auth failures and transient failures
  - money and date formatting
- **Eval harness:** tested with a scripted fake model on two scenarios, to check scoring and report generation. Real model runs are not part of the test suite.
- **Live tests:** marked and skipped by default, run only explicitly after manual setup.
- **Prior art:**
  - `tests/test_graph.py` (graph with a fake LLM)
  - `tests/test_tool_retry.py` (retry and no-retry, interrupts inside tools, no-backoff fixture)
  - `tests/memory/` (memory components with temporary stores)
- The full suite must pass with no network access and no credentials.

## Out of Scope

- Retiring Gmail and Google Calendar.
- Learning materials: phase notebooks, Learning-checkpoint answers, master plan and CLAUDE.md updates.
- Portfolio write-ups for 3.4 (context-pressure findings) and 4.4 (prompt-engineering findings). The owner writes these from their own understanding; the harness and traces supply the numbers.
- Phase 8 (Streamlit/FastAPI UI) and Phase 9 (aisuite). Multi-model use is done through LangChain's own chat-model abstraction.
- Sending mail, or any MS365 write other than the two draft tools.
- Any Informer write (creating or sending invoices, relations, bookings).
- Eval scenarios on real ITtopia data. A later step, once the owner has curated expected outcomes.
- Models beyond Gemini 3.8 Flash and Claude Sonnet 5.5 in the comparison.
- Payments or bank transactions and VAT returns. The Informer API has no endpoints for them.

## Further Notes

- **Order of work.** Everything else assumes the new model and dependencies, so the model and dependency update comes first. The fail-closed classification must land before any MS365 write tool is enabled.
- **Build vs live use.** The build needs no credentials, because every test and eval runs on the Fixture world. The owner's one manual task (the setup wizard) can run before or after the build. It must run before the live smoke check and before daily use.
- **Facts from the 2026-10-07 research** (recheck when implementing):
  - Informer API v2 base `https://api.informer.eu/v2`, `Apikey` + `Securitycode` headers, 60/min and 5000/day, `page`/`records` pagination with a `pagination` object.
  - Sales invoice fields: `expiry_date`, `totals.open`.
  - There is no sandbox; the Fixture world is the only safe test target.
  - MS365 server 0.159.1, with write tool names as listed above.
  - `mcp` 2.x is incompatible with `langchain-mcp-adapters` 0.3.x.
  - `gemini-2.0-flash` was shut down on 2026-06-01.
- **Automated run boundary.** Ticket 01 is the owner's manual setup (`ready-for-human`). An automated `/implement-spec` run implements every ticket not blocked by 01, which is tickets 02–15. It treats ticket 01, and tickets 16 and 17 that depend on it, as outside the run: it does not wait for them, and it reports them as pending. Run 16 and 17 after the owner completes 01.
- The integration branch is `feat/complete-phases-5-7`. The workflow never merges to `main`; the owner reviews and merges.
