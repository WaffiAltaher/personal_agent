# 27: Dependency and MS365 startup cleanup

**Type:** task

**Model:** Haiku

**Blocked by:** 11

**Status:** resolved

**Closes:** E5, E4 second half

**What to build:** Upgrade the checkpoint library to the version that fixes its import-time deprecation warning, provided the lock file resolves with the pinned LangGraph. Startup reuses one Microsoft 365 session for loading tools and checking the login, so the server starts once instead of twice.

- [x] The deprecation warning no longer appears on import; the lock file resolves; the full suite passes
- [x] Test: startup launches the MS365 server once
- [x] If the upgrade doesn't resolve with the pinned LangGraph, stop and report instead of changing LangGraph

Spec: `../spec.md`. Decisions: `../findings.md` ("Decisions taken").

## Comments

- Resolved on `ticket/27-ms365-startup`. `langgraph-checkpoint` upgraded 4.0.1 → 4.3.0 in `uv.lock` (`uv lock --upgrade-package langgraph-checkpoint`); LangGraph stays 1.1.6. The import-time `allowed_objects` deprecation warning is gone.
- Startup (`src/agent/tools/mcp_loader.py`) now opens one MS365 (or any server's) session for both the tool listing and the login check, so the server starts once. Tools still open their own session per call, so they work after startup.
- The login-failure notice is raised after the session closes, so it isn't wrapped in the session's task group (the boundary-failure test caught this).
- `tests/test_ms365_startup_once.py`: kept the launch-count test. The second test named `ms365_get-mailbox-settings`, which the Fixture world doesn't have, so it is now `ms365_list-outlook-contacts`.
- Full default suite: 283 passed, 1 deselected (live).
