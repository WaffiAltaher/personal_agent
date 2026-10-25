# 08: Spike: can `cursor-agent` be a safe chat model?

**Type:** research

**Blocked by:** 02

**Status:** needs-triage

**Question:** Can `cursor-agent -p` be locked down enough to serve as a chat model under the ADR-016 contract (stateless calls, JSON messages in, validated JSON reply out), so that the owner's Cursor subscription gives access to its other models (GPT-5.6, Codex 5.3, Grok, Gemini 3.7 Flash)?

What is known (2026-10-25, `cursor-agent` 2026.08.31):
- `-p` "has access to all tools, including write and shell". There is no flag to turn tools off.
- The closest lock-down is `--mode ask` (read-only) plus `--sandbox enabled` and `--workspace <empty temp dir>`.
- It has no system-prompt flag and no schema flag, so the reply format rests on the prompt alone.
- `--output-format json` exists.

To find out, by running it:
- With `--mode ask`, sandbox and an empty workspace, can a prompt-injected instruction still make it read a file outside the workspace, search the web, or fetch a URL?
- Does it keep to the JSON reply contract over a range of models, and how often does a re-ask fix a bad reply?
- Does it load the owner's own Cursor rules or MCP servers, and can that be stopped?
- How does it authenticate, and can an API key in the environment change billing?
- What do usage and the reported model look like in its JSON output?

**Answer expected:** go or no-go, with the exact flags if go, and the test runs that back it.

Spec: `../spec.md` (Out of Scope); ADR-016 (Cursor deferred).
