# 27: Dependency and MS365 startup cleanup

**Type:** task

**Model:** Haiku

**Blocked by:** 11

**Status:** ready-for-agent

**Closes:** E5, E4 second half

**What to build:** Upgrade the checkpoint library to the version that fixes its import-time deprecation warning, provided the lock file resolves with the pinned LangGraph. Startup reuses one Microsoft 365 session for loading tools and checking the login, so the server starts once instead of twice.

- [ ] The deprecation warning no longer appears on import; the lock file resolves; the full suite passes
- [ ] Test: startup launches the MS365 server once
- [ ] If the upgrade doesn't resolve with the pinned LangGraph, stop and report instead of changing LangGraph

Spec: `../spec.md`. Decisions: `../findings.md` ("Decisions taken").
