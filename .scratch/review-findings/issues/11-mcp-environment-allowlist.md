# 11: MCP server environment allowlist

**Type:** task

**Model:** Haiku

**Blocked by:** None (can start immediately)

**Status:** claimed

**Closes:** F3, F4, E4 first half (k92)

**What to build:** Each MCP server receives only an allowlisted environment: system basics (path, home, and the variables Node and npx need) plus its own settings (Microsoft 365 settings for MS365, Informer settings for Informer, the Fixture-world date for stand-ins). The Microsoft 365 server starts with a working directory outside the repo, so it can't read the repo's `.env`. The existing keytar test, whose setup removed the very variable it checked, is fixed so it can fail.

- [ ] Killing test `k92` (keytar opt-out in the shell never reaches the server) added and passing
- [ ] Test: a made-up secret variable in the environment is absent from every server's environment
- [ ] Test: the MS365 server's working directory is outside the repo
- [ ] The existing keytar test sets the variable before asserting it's absent
- [ ] Fixture-world MCP tests still pass (the stand-ins still start)

## Notes for the implementer

Trap: npx needs some environment to run. If a Fixture-world or MS365 test fails to start a server, add the specific variable it needs to the allowlist with a comment; never fall back to passing everything. Derive the Informer server's own variables from its settings rather than a hand-kept list, so settings added later (ticket 16's hand-over transport, upload log and size cap) pass without editing the allowlist.

Spec: `../spec.md`. Decisions: `../findings.md` ("Decisions taken").
