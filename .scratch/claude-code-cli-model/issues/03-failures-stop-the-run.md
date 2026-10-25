# 03: Usage limit, timeout and CLI errors stop the run, which can be resumed

**What to build:** When a Claude Code call can't produce a turn, the owner's run stops with a message they can act on, and the run can be resumed later. Nothing is retried, nothing falls back to an API key or another model, and nothing waits.

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] Usage limit: the run stops with "Claude subscription usage limit reached; resets at <time>. The run is saved and can be resumed."
- [ ] Timeout (`CLAUDE_CODE_TIMEOUT_S`): the CLI process and anything it started are killed, and the run stops with "Claude Code did not answer within <n> s; the run is saved and can be resumed."
- [ ] A non-zero exit, an error result, unparseable output and an unknown model each stop with the CLI's own message
- [ ] If ticket 02 has landed, a reply still invalid after the re-ask uses this same stop path
- [ ] None of these is retried, and none falls back to another model
- [ ] The agent CLI shows the message, not a traceback
- [ ] Graph test: after a usage-limit stop, the thread resumes from its checkpoint once the stand-in answers normally
- [ ] The whole test suite passes

Traps:
- Nobody has seen the exact usage-limit result yet. Detect it as well as the known result fields allow, and leave a note that the real text must be pinned in the stand-in the first time it happens.
- A killed child can leave its own children running. Kill the whole process group, and check in the test that the stand-in is gone.

Spec: `../spec.md` (Failures).
