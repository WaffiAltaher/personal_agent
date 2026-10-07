# 05: MS365 Drafts behind approval

**What to build:** The owner can ask the agent to summarise mail on a topic and propose a reply. The reply appears as a Draft in Outlook only after the owner approves it, and the agent cannot send anything. The server pin is bumped to the current exact version and `--read-only` is dropped. The model sees exactly the read tools plus `create-draft-email` and `create-reply-draft`. Every other write (send, delete, move, update, calendar changes, rules, folders, permissions) is unreachable.

**Blocked by:** 03, 04

**Status:** ready-for-agent

- [x] `@softeria/ms-365-mcp-server` pinned to an exact current version (0.159.1 when researched; recheck)
- [x] A test asserts the exact set of bound MS365 tool names against the stand-in; login and account-management tools stay hidden
- [x] The stand-in implements both draft tools and records the Drafts it creates
- [x] A seam-A test of the inbox-triage flow: approval creates the Draft; rejection creates none and is acknowledged; a transient error on a draft call is not retried
- [x] New optional setting for the expected MS365 username, passed to the server
- [x] The macOS keychain token cache is left enabled
- [x] ADR-005 amended: `Mail.ReadWrite` scope for Drafts, sending still excluded

## Comments

- 2026-10-07: 0.159.1 is still the latest release. `--read-only --preset outlook` is replaced by `--enabled-tools` with an anchored pattern of exact names (a preset would override that flag; `ENABLED_TOOLS` is stripped from the server env for the same reason). The loader also binds only `ms365_mcp.EXPOSED_TOOLS` by name (`McpServer.exposed_tools`) and classifies MS365 reads by `read_allowlist` instead of trusting `readOnlyHint`. The stand-in serves 18 other writes plus `download-bytes-to-file` (which the real server annotates readOnlyHint although it writes a local file), and the exact-set test shows none of them is bound. Draft tool signatures (real server): `create-draft-email(body: Message)`, `create-reply-draft(messageId, body: {Comment | Message})`. The stand-in records each draft call as a JSON line in `$FIXTURE_WORLD_MS365_DRAFTS`; tests read it back with `fixture_world.ms365.recorded_drafts()` / `recorded_draft_calls()`. `FIXTURE_WORLD_MS365_DRAFT_FAILURE=transient` makes draft calls fail with a Graph 503 in the real server's error format. New setting `MS365_MCP_EXPECTED_USERNAME`. ADR-010 got a one-line amendment for the change to name-based classification.
