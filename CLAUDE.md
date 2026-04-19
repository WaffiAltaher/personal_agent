# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies
uv sync

# Run the agent
python -m agent.cli "<question>"

# Run all tests
pytest tests/

# Run a single test file
pytest tests/test_tools.py -v

# Run a single test
pytest tests/test_tools.py::test_read_file -v
```

## Architecture

This is a personal data agent built on LangGraph with a ReAct (Reason + Act) loop. It connects to Gmail, Google Calendar, local files, and web search (Tavily), then reasons over them using Gemini 2.0 Flash.

### Core flow

```
CLI → graph.py (LangGraph) → agent_node (LLM) → human_review_node → tools_with_fallback → agent_node ...
```

**`src/agent/graph.py`** — the heart of the agent. Key pieces:
- `AgentState`: a single `messages` list with `add_messages` reducer (appends, never overwrites)
- `agent_node`: calls Gemini with full message history
- `human_review_node`: gates write tools (draft email, calendar events) behind `interrupt()` — pauses the graph for user approval
- `tools_with_fallback`: wraps `ToolNode` with a fallback that injects error `ToolMessage`s on exhausted retries so the graph continues
- `RetryPolicy`: exponential backoff (1s, 2s, 4s) on transient errors (ConnectionError, TimeoutError, 429, 5xx only)
- `SqliteSaver` checkpoints to `checkpoints/hitl.db` keyed by `thread_id` — interrupted runs can resume

**`src/agent/cli.py`** — entry point. Drives the HITL loop: invoke graph → detect `__interrupt__` → show approval prompt → `Command(resume=decision)` → repeat.

**`src/agent/tools/`** — all tools return strings (success or `"Error: ..."` on failure, never raise). `ALL_TOOLS` in `__init__.py` is the registry passed to the graph.

**`src/agent/config.py`** — Pydantic Settings loading from `.env`. Required: `GOOGLE_API_KEY`, `TAVILY_API_KEY`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`.

**`src/agent/auth/google.py`** — OAuth2 for Gmail/Calendar. First run opens browser; token saved to `credentials/token.json` and auto-refreshes.

### Tool failure resilience (two layers)

1. **Retry policy** (LangGraph-level): retries transient errors with backoff; explicitly does NOT retry 4xx permanent errors
2. **Fallback** (node-level): catches exhausted retries, injects error ToolMessages so the graph keeps running rather than crashing

### Human-in-the-loop

`TOOLS_REQUIRING_APPROVAL` set in `graph.py` controls which tools need approval. When the LLM calls one, `human_review_node` calls `interrupt()`. The CLI collects "approve"/"reject", resumes via `Command(resume=decision)`. On reject, a rejection `ToolMessage` is injected so the agent can acknowledge gracefully.

## Development notes

- Python 3.13, managed with `uv`
- No linter is configured yet (pylint/flake8 disabled in `.vscode/settings.json`)
- Langfuse traces to `http://localhost:3000` by default — needs a local Langfuse instance running
- Google credentials file must be manually downloaded from GCP console and placed at `credentials/google_credentials.json`
- The `credentials/` and `checkpoints/` directories are gitignored
- Phase roadmap is in `docs/MASTER_PLAN.md` — currently completed through Phase 2 (HITL + checkpointing)
