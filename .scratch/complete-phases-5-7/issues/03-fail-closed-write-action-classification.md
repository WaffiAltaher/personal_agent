# 03: Approval fails closed (Write-action classification)

**What to build:** Every tool bound to the graph is classified as read or Write action when tools are loaded. Anything unclassified is treated as a Write action: it goes through the approval gate and is never retried automatically. This replaces the hand-maintained set of names that require approval, which fixes the known issue where the `ms365_` prefix let MS365 writes bypass approval. Gmail and Google Calendar stay in the agent. Gmail's draft tool is a Write action and its read tools are read.

**Blocked by:** 02

**Status:** ready-for-agent

- [ ] Local tools declare their classification explicitly
- [ ] MCP tools are read only if they are on an explicit read allowlist or carry a trusted read-only annotation; everything else is a Write action
- [ ] A test asserts every tool bound to the graph is either read-classified or gated by approval
- [ ] A test proves an unknown tool name pauses for approval and is not retried on a transient error
- [ ] The known-issues entry for MS365 approval is removed
- [ ] ADR appended: fail-closed classification
