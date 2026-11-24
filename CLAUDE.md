# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies
uv sync

# Run the agent: a session that answers the optional first question, then reads Follow-ups at `> `
# (exit, quit or Ctrl-D ends it). Add --fixtures to run against the seeded Fixture world instead of real data.
# --resume <id> continues an earlier Conversation (the id is printed at start and exit); a bare --resume the most recent.
python -m agent.cli [--resume [<id>]] ["<first question>"]

# Web interface (real data only) on http://127.0.0.1:<WEB_PORT>: set the password once, build the app, start the server
python -m agent.web.set_password
cd web && npm install && npm run build   # produces web/dist, which the server serves
python -m agent.web
# Front-end development: the Vite dev server on :5173 proxies /api to the running server
cd web && npm run dev

# Log in to Google (Gmail/Calendar) when startup says the token is missing or dead
python -m agent.auth.google

# Log in to Claude Code (claude_code: models) when startup says it is not logged in
claude auth login

# Run evals against the Fixture world; compare two result files
python -m agent.evals --model <provider:model> --judge-model <provider:model> [--repeats N]
python -m agent.evals compare a.json b.json

# Tests. In a worktree, run `uv sync` first so the editable install points at that worktree.
uv run pytest
uv run pytest tests/test_tools.py -v
uv run pytest tests/test_tools.py::test_read_file -v

# Browser journeys (tests/web/test_web_browser.py, marker `browser`): Playwright drives web/dist on the Fixture tools and a stand-in model, no live calls.
# They need the built app and a browser, and are skipped (naming the install command) without a browser.
cd web && npm run build && cd ..
uv run playwright install chromium
uv run pytest tests/web/test_web_browser.py
# Everything but the journeys. Keep `not live`: a -m on the command line replaces the default
# `-m "not live"`, and live tests call the real Claude Code and MS365.
uv run pytest -m "not live and not browser"
```

## Architecture

This is a personal data agent built on LangGraph with a ReAct (Reason + Act) loop. It connects to Microsoft 365 (Outlook mail/calendar/contacts and the OneDrive Invoice archive, via the third-party `@softeria/ms-365-mcp-server`), Informer accounting (via the self-authored MCP server in `src/informer_mcp/`), Gmail, Google Calendar, local files, and web search (Tavily). The model is chosen by `MODEL_NAME` as `provider:model` (default `claude_code:claude-sonnet-5-5`, the owner's Claude subscription through the Claude Code CLI, ADR-016; `google_genai:` and `anthropic:` models also supported). Business vocabulary is in `GLOSSARY.md`.

### Core flow

```
CLI → graph.py (LangGraph) → agent_node (LLM) → human_review_node → tools_with_fallback → agent_node ...
```

**`src/agent/graph.py`** — the heart of the agent. Key pieces:
- `AgentState`: a single `messages` list with the `add_messages` reducer (messages merge by id; a new id is appended)
- `agent_node`: calls the chat model with full message history; `build_graph(checkpointer, tools, model)` accepts an injected model (tests and evals use this)
- `human_review_node`: gates Write actions (any tool not classified read) behind `interrupt()` — pauses the graph for user approval
- `tools_with_fallback`: wraps `ToolNode` with a fallback that injects error `ToolMessage`s on exhausted retries so the graph continues
- `retry_tool_call` + `TOOL_RETRY_POLICY`: per-tool-call backoff (up to 3 attempts) on transient errors (ConnectionError, TimeoutError, 429, 5xx only); Write actions are never retried
- `SqliteSaver` checkpoints to `checkpoints/hitl.db` (`checkpoints/fixtures.db` for `--fixtures`) keyed by `thread_id` — interrupted runs and `--resume`d Conversations continue from them

**`src/agent/cli.py`** — entry point. Runs a session: each line at `> ` is a Follow-up in one Conversation (one thread), whose one run log entry is written after every turn (and once more at exit), built from the thread by `write_run_log(db_path, thread_id)` (keyed by thread id, so each write replaces the entry and keeps earlier errors, also from a `--resume`d session). Ctrl-C cancels a running turn; outside a turn and a prompt it ends the session, which still writes the entry. Drives the HITL loop: invoke graph → detect `__interrupt__` → show approval prompt → `Command(resume=decision)` → repeat.

**`src/agent/turn_rules.py`** — what the CLI and the web server do the same way around a turn: `write_run_log`, the run config (`run_config`), the Langfuse trace id and attributes (`trace_id`, `trace_attributes`, `OWNER_USER_ID`), and the message and run log error of a known failure (`KNOWN_FAILURES`, `known_failure`, `STEP_LIMIT_STOPPED`). The web package must not import `agent.cli`.

**`src/agent/tools/`** — local tools return strings (success or `"Error: ..."` on failure) and raise only transient failures (`transient.py`: network blips, HTTP 429/5xx), so the graph retries them. `LOCAL_TOOLS` in `__init__.py` lists local tools, each wrapped in `read_tool(...)`, `outbound_read(...)` or `write_action(...)` (`classification.py`). `load_all_tools(fixtures=...)` adds MCP tools from the servers in `mcp_servers()`, loaded by `mcp_loader.py` (prefixed `ms365_` / `informer_`, classified per server; a server that fails to start is skipped with a notice). `read_pdf_text` (`pdf_text.py`) is a local read of a PDF's text, for the invoice date. The MS365 server's drive tools are enabled but never bound: the model reaches OneDrive only through three agent-side tools fixed to the Invoice archive (`ms365_invoice_archive.py`, ADR-020): the reads `ms365_list_invoice_archive` and `ms365_check_invoice_archive` (the Processed check) and the Write action `ms365_upload_to_onedrive`.

**`src/agent/web/`** — the web interface beside the CLI (ADR-018). `create_app(graph=, tools=, model=, checkpoint_path=, web=WebConfig(...))` builds the FastAPI app, so tests inject the Fixture world and the stand-in model; `server.py` runs the startup and uvicorn. Endpoints that need the owner depend on `require_session`; `RequestChecks` refuses a foreign `Host` everywhere and a foreign or missing `Origin` on state-changing requests and event streams. The React app (Vite, TypeScript) is in top-level `web/`. Startup steps shared with the CLI, with the same messages, are in `src/agent/startup.py`.

**`src/fixture_world/`** — seeded stand-ins (MS365 MCP server, fake Informer API, web search) used by tests, evals and `--fixtures`.

**`src/agent/evals/`** — eval harness: scenarios over the Fixture world, trajectory metrics, RAGAS generation metrics, cost/latency, model-comparison reports.

**`src/agent/config.py`** — Pydantic Settings loading from `.env`. Required: `GOOGLE_API_KEY` (embeddings; use a key from a Google project with billing turned off), `TAVILY_API_KEY`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`. Optional: `ANTHROPIC_API_KEY` (required for `anthropic:` models), `CLAUDE_CODE_BINARY` and `CLAUDE_CODE_TIMEOUT_S` (`claude_code:` models), `MODEL_TIMEOUT_S` (per API request for `google_genai:`/`anthropic:` models and embeddings; default 120), `MODEL_ATTEMPTS` (tries per failed request, first included, for every model and the embeddings; default 2), `MS365_MCP_*`, `INFORMER_*` (the agent also reads `INFORMER_DOWNLOADS_DIR`, the Downloads folder the Invoice archive tools take files from), `INFORMER_INCOMING_ADDRESS` and `INFORMER_INVOICE_MAILBOX` (the Informer server's e-mail hand-over of Purchase invoices, ADR-019: the Informer incoming address and the Invoice mailbox it is sent from; the upload tools appear only when both are set, with the `MS365_MCP_*` client and tenant IDs the server gets from the agent; the incoming address works like a write key to the books, so keep both in `.env` and never commit them; the wizard's optional Informer e-mail step writes them), `EVAL_JUDGE_MODEL`, `WEB_PASSWORD_HASH` (set by `python -m agent.web.set_password`; the web server needs it), `WEB_PORT` (default 8000), `WEB_HOST` (bind host, default `127.0.0.1`; keep it until Sign in with Google replaces the password).

**`src/agent/auth/claude_code.py`** — Claude Code login check. With a `claude_code:` agent or judge model, real-mode CLI startup runs `claude auth status` and stops unless it is logged in with a claude.ai subscription, naming `claude auth login`. Tests never call the real `claude`: they point `CLAUDE_CODE_BINARY` at the stand-in `src/fixture_world/claude_code.py`, and `tests/conftest.py` sets it to a missing binary otherwise.

**`src/agent/auth/google.py`** — OAuth2 for Gmail/Calendar. Real-mode CLI startup checks the token before the run; a missing or dead refresh token stops startup and names `python -m agent.auth.google` (the only command that opens a browser). Token saved to `credentials/token.json` and auto-refreshes while valid. Testing-mode refresh tokens expire seven days after issue, regardless of use.

### Tool failure resilience (two layers)

1. **Retry policy** (LangGraph-level): retries transient errors with backoff; explicitly does NOT retry 4xx permanent errors
2. **Fallback** (node-level): catches exhausted retries, injects error ToolMessages so the graph keeps running rather than crashing

### Human-in-the-loop

Approval **fails closed**: every bound tool is classified read or Write action (`src/agent/tools/classification.py`, ADR-010). Local tools declare it with `read_tool(...)` / `write_action(...)`; MCP tools are read only if on their server's explicit read allowlist. Anything unclassified is a Write action. **A new tool that changes external data must be wrapped in `write_action(...)` — never `read_tool(...)`, or it would run without approval and be retried.** A read that sends text the model wrote to a service outside the owner's accounts (today only web search) is an **Outbound read**: wrap it in `outbound_read(...)`. It runs like a read until the conversation holds a result from any other tool, then it needs Approval too, so an injected instruction can't carry the owner's data out in a query (ADR-017). When the LLM calls a Write action or a gated Outbound read, `human_review_node` calls `interrupt()`. The CLI collects "approve"/"reject", resumes via `Command(resume=decision)`. On reject, a rejection `ToolMessage` is injected so the agent can acknowledge gracefully.

## Development notes

- Python 3.13, managed with `uv`
- Live credentials setup (Claude Code login, Google key, optional Gemini/Anthropic, Informer, Azure/MS365 login, Langfuse): run `./scripts/setup_wizard.sh`
- No linter is configured yet (pylint/flake8 disabled in `.vscode/settings.json`)
- Langfuse traces to `http://localhost:3000` by default — needs a local Langfuse instance running
- Google credentials file must be manually downloaded from GCP console and placed at `credentials/google_credentials.json`
- The `credentials/` and `checkpoints/` directories are gitignored
- `notebooks/`, `.claude/skills/`, and the rest of `docs/` are gitignored. A worktree does not have those. Read them from the primary checkout (`git worktree list`). `docs/agents/` and `docs/ARCHITECTURE_DECISIONS.md` are tracked.
- An MCP child sees only its allowlisted environment. A new variable is `FIXTURE_WORLD_*` or one of that server's own settings.
- Phase roadmap is in `docs/MASTER_PLAN.md`. Phases 5–7 are on main (spec and tickets in `.scratch/complete-phases-5-7/`)

## Agent skills

### Issue tracker

Local markdown under `.scratch/<feature-slug>/`. See `docs/agents/issue-tracker.md`.

### Triage labels

Default five canonical labels. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: root `GLOSSARY.md` (business domain) + ADRs in `docs/ARCHITECTURE_DECISIONS.md`. See `docs/agents/domain.md`.
