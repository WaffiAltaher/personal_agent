# 06: Failures at the MCP boundary

**What to build:** A broken MCP integration never takes the agent down:
- A server that fails to start leaves the agent running with its remaining tools, plus a notice naming the unavailable integration and why.
- A missing or expired MS365 login becomes a message naming the login command.
- A tool error reported through MCP, or a crash in the middle of a run, reaches the model as an error ToolMessage.
- Transient errors are retried on read tools only.
- MCP tool calls appear as clearly named spans in Langfuse.

**Blocked by:** 04

**Status:** ready-for-agent

- [ ] Seam-A tests for: server down at startup, auth failure at startup, a tool error reported through MCP, a server crash in the middle of a run
- [ ] A transient MCP read error is retried; a permanent error is not
- [ ] The stand-in MS365 server can be switched into each failure mode
- [ ] MCP tool spans carry the prefixed tool name in Langfuse traces
