# 04: MCP loader + Fixture world (stand-in MS365) + `--fixtures` flag

**What to build:** One loader starts all configured MCP servers through `langchain-mcp-adapters` with server-name prefixes, each server optional and isolated. The Fixture world gets its first piece: a small local MCP server that stands in for MS365. It uses the real server's tool names and response shapes for the read tools the agent needs (mail, calendar, contacts) and serves a seeded mailbox, calendar and contacts. A CLI flag runs the agent against the Fixture world. Demo: with `--fixtures`, "what meetings do I have this week and who is attending?" is answered by combining calendar, contacts and mail (plan item 5.3).

**Blocked by:** 02

**Status:** resolved

- [x] Seed data is in versioned fixture files
- [x] The stand-in MS365 server reproduces the real tool names and shapes for the tools used
- [x] The CLI `--fixtures` flag points the loader at the Fixture world
- [x] A seam-A test (scripted model) runs the meetings-and-attendees flow against the stand-in over real MCP
- [x] ADR appended: Fixture world as the only test and eval target (Informer has no sandbox)

## Comments

- Loader: `agent/tools/mcp_loader.py` — `McpServer(name, connection, unavailable_reason, hidden_tools, read_allowlist, trust_read_only_hint)` and `load_mcp_tools(servers) -> (tools, notices)`. Servers load concurrently and in isolation; `connection=None` or a start failure becomes a notice. Classification (ADR-010) runs per server inside the loader. Server lists live in `agent.tools.mcp_servers(fixtures=...)`; `load_all_tools(fixtures=...)` now returns `(tools, notices)` and the CLI prints the notices. MS365 client/tenant settings are optional (missing → notice).
- Stand-in: `fixture_world/ms365.py` (run `python -m fixture_world.ms365`), seed in `fixture_world/data/ms365/`. Seven read tools (calendar view/events/event, mail messages/message, contacts/contact) with the real names, params, `readOnlyHint` annotations and indent-2 Graph JSON bodies; plus the account tools so their hiding is testable (`list-accounts` is now hidden too). Add tools with `graph_tool(name, description, read_only=False)` inside `create_server`.
- `fixture_world.clock`: seeded dates move by whole weeks onto the current week; `FIXTURE_WORLD_TODAY` pins it. The fixture connection passes `os.environ` through.
- Each tool call spawns a fresh stand-in process, so ticket 05's recorded Drafts need to live outside the process (e.g. a file named by an env var).
- With `--fixtures`, the Google tools and web search are still the real ones; only MCP servers switch.
- Real server unchanged otherwise (0.119.0, `--read-only`); ADR-011 records the Fixture world.
