# 03: Approval fails closed (Write-action classification)

**What to build:** Every tool bound to the graph is classified as read or Write action when tools are loaded. Anything unclassified is treated as a Write action: it goes through the approval gate and is never retried automatically. This replaces the hand-maintained set of names that require approval, which fixes the known issue where the `ms365_` prefix let MS365 writes bypass approval. Gmail and Google Calendar stay in the agent. Gmail's draft tool is a Write action and its read tools are read.

**Blocked by:** 02

**Status:** resolved

- [x] Local tools declare their classification explicitly
- [x] MCP tools are read only if they are on an explicit read allowlist or carry a trusted read-only annotation; everything else is a Write action
- [x] A test asserts every tool bound to the graph is either read-classified or gated by approval
- [x] A test proves an unknown tool name pauses for approval and is not retried on a transient error
- [x] The known-issues entry for MS365 approval is removed
- [x] ADR appended: fail-closed classification

## Comments

- Implemented in `src/agent/tools/classification.py`: `read_tool` / `write_action` (local tools, declared in `LOCAL_TOOLS`), `classify_mcp_tools(tools, *, read_allowlist=(), trust_read_only_hint=False)` (call once per MCP server in the loader; allowlist uses bound, prefixed names), `is_read(tool)`. Class is stored in tool metadata under `action_class`.
- `graph.py` no longer has `TOOLS_REQUIRING_APPROVAL`: approval and no-retry both key off the bound tools' classification; unclassified or unknown names are Write actions. MS365 loader trusts `readOnlyHint` (server sets it from the HTTP method).
- Tests: `tests/test_write_action_classification.py` (seam A). Ad-hoc test tools in existing tests now declare `read_tool`. ADR-010 appended.
