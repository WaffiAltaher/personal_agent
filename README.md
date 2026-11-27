# Personal Data Agent

A personal AI agent to help manage a small business. It answers questions and does admin work
across the owner's own data: Microsoft 365 (Outlook mail, calendar, contacts, OneDrive), Gmail and
Google Calendar, Informer accounting, local files and web search.

Built on [LangGraph](https://github.com/langchain-ai/langgraph) as a ReAct agent, with a CLI and a
small web interface.

## Highlights

- **Human in the loop, fail-closed.** Every tool is classified as a read or a Write action. Anything
  that changes external data, or that sends text the model wrote to a service outside the owner's
  accounts once private data is in the conversation, pauses for explicit approval.
- **MCP integrations.** Microsoft 365 through `@softeria/ms-365-mcp-server`, and a custom-built MCP
  server for the Informer accounting API.
- **Resilient tool calls.** Retries with backoff on transient errors only, and a fallback that
  turns exhausted retries into an error the agent can reason about, so a run never crashes.
- **Resumable conversations.** State is checkpointed to SQLite, so interrupted runs and earlier
  conversations pick up where they left off.
- **Evals.** A seeded fixture world (fake MS365, Informer and search) drives an eval harness with
  trajectory metrics, RAGAS generation metrics, cost/latency tracking and model comparison.
- **Model choice.** Claude (via the Claude Code CLI or the Anthropic API) or Gemini, picked with
  `MODEL_NAME`. Traces go to Langfuse.

## Quick start

Requires Python 3.13 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
./scripts/setup_wizard.sh      # walks through credentials
python -m agent.cli --fixtures "Which open invoices are not overdue yet, and for how much?"   # try it on fake data
python -m agent.cli            # real data
```

Run the tests with `uv run pytest`.

## Learn more

- [`CLAUDE.md`](CLAUDE.md): architecture and commands
- [`GLOSSARY.md`](GLOSSARY.md): business vocabulary
- [`docs/ARCHITECTURE_DECISIONS.md`](docs/ARCHITECTURE_DECISIONS.md): design decisions (ADRs)
