# 05: MS365 Drafts behind approval

**What to build:** The owner can ask the agent to summarise mail on a topic and propose a reply. The reply appears as a Draft in Outlook only after the owner approves it, and the agent cannot send anything. The server pin is bumped to the current exact version and `--read-only` is dropped. The model sees exactly the read tools plus `create-draft-email` and `create-reply-draft`. Every other write (send, delete, move, update, calendar changes, rules, folders, permissions) is unreachable.

**Blocked by:** 03, 04

**Status:** ready-for-agent

- [ ] `@softeria/ms-365-mcp-server` pinned to an exact current version (0.159.1 when researched; recheck)
- [ ] A test asserts the exact set of bound MS365 tool names against the stand-in; login and account-management tools stay hidden
- [ ] The stand-in implements both draft tools and records the Drafts it creates
- [ ] A seam-A test of the inbox-triage flow: approval creates the Draft; rejection creates none and is acknowledged; a transient error on a draft call is not retried
- [ ] New optional setting for the expected MS365 username, passed to the server
- [ ] The macOS keychain token cache is left enabled
- [ ] ADR-005 amended: `Mail.ReadWrite` scope for Drafts, sending still excluded
