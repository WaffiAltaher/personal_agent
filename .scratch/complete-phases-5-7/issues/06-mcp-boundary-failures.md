# 06: Failures at the MCP boundary

**What to build:** A broken MCP integration never takes the agent down:
- A server that fails to start leaves the agent running with its remaining tools, plus a notice naming the unavailable integration and why.
- A missing or expired MS365 login becomes a message naming the login command.
- A tool error reported through MCP, or a crash in the middle of a run, reaches the model as an error ToolMessage.
- Transient errors are retried on read tools only.
- MCP tool calls appear as clearly named spans in Langfuse.

**Blocked by:** 04

**Status:** ready-for-agent

- [x] Seam-A tests for: server down at startup, auth failure at startup, a tool error reported through MCP, a server crash in the middle of a run
- [x] A transient MCP read error is retried; a permanent error is not
- [x] The stand-in MS365 server can be switched into each failure mode
- [x] MCP tool spans carry the prefixed tool name in Langfuse traces

## Comments

- Done. Tests: `tests/test_mcp_boundary_failures.py` (seam A, against the stand-in over stdio; no real backoff).
- Boundary mapping lives in `agent/tools/mcp_loader.py`, configured per `McpServer`: `login: LoginCheck` (startup check tool, service, login command, error patterns) and `transient_errors` (regexes over tool-error text). A matching tool error, or a server that closed the connection mid-call, is raised as `TransientMcpError`, which `graph._should_retry` treats as transient (read tools only); other tool errors reach the model as error ToolMessages, unretried; login errors name the login command.
- Failure-injection knob (for ticket 13): `fixture_world.ms365.FailureSwitch(path)`. Put `switch.env` (`FIXTURE_WORLD_MS365_FAILURE_FILE`) in the environment before loading tools, then `switch.set(mode, times=None)` / `switch.clear()` at any time, even mid-run (every stand-in process re-reads it; `times` counts down). Modes (`fixture_world.ms365.Failure`): `down`, `logged-out`, `tool-error`, `transient`, `crash`. `FIXTURE_WORLD_MS365_FAILURE=<mode>` fixes a mode from the shell.
- Langfuse tool spans already carry the prefixed name (`ms365_list-outlook-contacts`); verified through `agent.tracing.get_callback_handler` with an in-memory OTel exporter.
