# 04: Failures keep the session

**What to build:** A failed turn no longer ends the session when the failure is one we know. A Claude Code error (timeout, crash, usage limit, invalid reply, ADR-016) or the step limit prints the same `Stopped: …` line as today and returns to `> `; the next question continues the same Conversation. (Checked: these errors are raised at the model call before the node writes anything, so the thread ends on answered messages and accepts a new one.) An unexpected exception still ends the session: it writes the run log entry with the error, prints the traceback and a resume hint naming the Conversation id (`--resume <id>` once 03 lands; until then, the id), and exits non-zero.

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] A Claude Code error mid-session prints `Stopped: …` and returns to `> `; a following question is answered on the same thread
- [ ] The step limit does the same
- [ ] An unexpected exception writes the run log entry with the error, prints the traceback and the Conversation id / resume hint, exits non-zero
- [ ] The run log entry written at the end of a session that had a known failure records it
- [ ] Tested through the shared CLI harness with a scripted model

## Comments
