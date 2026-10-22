# 11: MCP server environment allowlist

**Type:** task

**Model:** Haiku

**Blocked by:** None (can start immediately)

**Status:** resolved

**Closes:** F3, F4, E4 first half (k92)

**What to build:** Each MCP server receives only an allowlisted environment: system basics (path, home, and the variables Node and npx need) plus its own settings (Microsoft 365 settings for MS365, Informer settings for Informer, the Fixture-world date for stand-ins). The Microsoft 365 server starts with a working directory outside the repo, so it can't read the repo's `.env`. The existing keytar test, whose setup removed the very variable it checked, is fixed so it can fail.

- [x] Killing test `k92` (keytar opt-out in the shell never reaches the server) added and passing
- [x] Test: a made-up secret variable in the environment is absent from every server's environment
- [x] Test: the MS365 server's working directory is outside the repo
- [x] The existing keytar test sets the variable before asserting it's absent
- [x] Fixture-world MCP tests still pass (the stand-ins still start)

## Notes for the implementer

Trap: npx needs some environment to run. If a Fixture-world or MS365 test fails to start a server, add the specific variable it needs to the allowlist with a comment; never fall back to passing everything. Derive the Informer server's own variables from its settings rather than a hand-kept list, so settings added later (ticket 16's hand-over transport, upload log and size cap) pass without editing the allowlist.

Spec: `../spec.md`. Decisions: `../findings.md` ("Decisions taken").

## Comments

- Resolved on `ticket/11-mcp-allowlist`. Each MCP server now gets an allowlisted environment (`src/agent/tools/mcp_environment.py`): system basics, plus its own settings. MS365 (real and stand-in) starts in the temp directory, outside the repo. Informer's own variables are derived from `InformerSettings`.
- The Fixture-world stand-ins get the `FIXTURE_WORLD_*` settings (clock, failure switches, draft log), not only the date; the boundary-failure tests need the switches.
- The `npx` launch was checked with only the system basics set; no extra variable was needed.
- Full suite on the merged branch: 258 passed, 1 deselected (live).
