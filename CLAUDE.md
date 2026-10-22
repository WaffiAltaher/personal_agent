# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies
uv sync

# Run the agent (add --fixtures to run against the seeded Fixture world instead of real data)
python -m agent.cli "<question>"

# Log in to Google (Gmail/Calendar) when startup says the token is missing or dead
python -m agent.auth.google

# Run evals against the Fixture world; compare two result files
python -m agent.evals --model <provider:model> --judge-model <provider:model> [--repeats N]
python -m agent.evals compare a.json b.json

# Tests. In a worktree, run `uv sync` first so the editable install points at that worktree.
uv run pytest
uv run pytest tests/test_tools.py -v
uv run pytest tests/test_tools.py::test_read_file -v
```

## Architecture

This is a personal data agent built on LangGraph with a ReAct (Reason + Act) loop. It connects to Microsoft 365 (Outlook mail/calendar/contacts, via the third-party `@softeria/ms-365-mcp-server`), Informer accounting (via the self-authored MCP server in `src/informer_mcp/`), Gmail, Google Calendar, local files, and web search (Tavily). The model is chosen by `MODEL_NAME` as `provider:model` (default `google_genai:gemini-3.8-flash`; `anthropic:` models also supported). Business vocabulary is in `GLOSSARY.md`.

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
- `SqliteSaver` checkpoints to `checkpoints/hitl.db` keyed by `thread_id` — interrupted runs can resume

**`src/agent/cli.py`** — entry point. Drives the HITL loop: invoke graph → detect `__interrupt__` → show approval prompt → `Command(resume=decision)` → repeat.

**`src/agent/tools/`** — local tools return strings (success or `"Error: ..."` on failure, never raise). `LOCAL_TOOLS` in `__init__.py` lists local tools, each wrapped in `read_tool(...)` or `write_action(...)` (`classification.py`). `load_all_tools(fixtures=...)` adds MCP tools from the servers in `mcp_servers()`, loaded by `mcp_loader.py` (prefixed `ms365_` / `informer_`, classified per server; a server that fails to start is skipped with a notice).

**`src/fixture_world/`** — seeded stand-ins (MS365 MCP server, fake Informer API, web search) used by tests, evals and `--fixtures`.

**`src/agent/evals/`** — eval harness: scenarios over the Fixture world, trajectory metrics, RAGAS generation metrics, cost/latency, model-comparison reports.

**`src/agent/config.py`** — Pydantic Settings loading from `.env`. Required: `GOOGLE_API_KEY`, `TAVILY_API_KEY`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`. Optional: `ANTHROPIC_API_KEY` (required for `anthropic:` models), `MS365_MCP_*`, `INFORMER_*`, `EVAL_JUDGE_MODEL`.

**`src/agent/auth/google.py`** — OAuth2 for Gmail/Calendar. Real-mode CLI startup checks the token before the run; a missing or dead refresh token stops startup and names `python -m agent.auth.google` (the only command that opens a browser). Token saved to `credentials/token.json` and auto-refreshes while valid. Testing-mode refresh tokens expire seven days after issue, regardless of use.

### Tool failure resilience (two layers)

1. **Retry policy** (LangGraph-level): retries transient errors with backoff; explicitly does NOT retry 4xx permanent errors
2. **Fallback** (node-level): catches exhausted retries, injects error ToolMessages so the graph keeps running rather than crashing

### Human-in-the-loop

Approval **fails closed**: every bound tool is classified read or Write action (`src/agent/tools/classification.py`, ADR-010). Local tools declare it with `read_tool(...)` / `write_action(...)`; MCP tools are read only if on their server's explicit read allowlist. Anything unclassified is a Write action. **A new tool that changes external data must be wrapped in `write_action(...)` — never `read_tool(...)`, or it would run without approval and be retried.** When the LLM calls a Write action, `human_review_node` calls `interrupt()`. The CLI collects "approve"/"reject", resumes via `Command(resume=decision)`. On reject, a rejection `ToolMessage` is injected so the agent can acknowledge gracefully.

## Development notes

- Python 3.13, managed with `uv`
- Live credentials setup (Gemini, Anthropic, Informer, Azure/MS365 login, Langfuse): run `./scripts/setup_wizard.sh`
- No linter is configured yet (pylint/flake8 disabled in `.vscode/settings.json`)
- Langfuse traces to `http://localhost:3000` by default — needs a local Langfuse instance running
- Google credentials file must be manually downloaded from GCP console and placed at `credentials/google_credentials.json`
- The `credentials/` and `checkpoints/` directories are gitignored
- `docs/`, `notebooks/`, and `.claude/skills/` are gitignored. A worktree does not have them. Read them from the primary checkout (`git worktree list`).
- An MCP child sees only its allowlisted environment. A new variable is `FIXTURE_WORLD_*` or one of that server's own settings.
- Phase roadmap is in `docs/MASTER_PLAN.md`. Phases 5–7 are implemented on `feat/complete-phases-5-7` (spec and tickets in `.scratch/complete-phases-5-7/`); live credentials setup (ticket 01) is still pending

## Agent skills

### Issue tracker

Local markdown under `.scratch/<feature-slug>/`. See `docs/agents/issue-tracker.md`.

### Triage labels

Default five canonical labels. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: root `GLOSSARY.md` (business domain) + ADRs in `docs/ARCHITECTURE_DECISIONS.md`. See `docs/agents/domain.md`.
