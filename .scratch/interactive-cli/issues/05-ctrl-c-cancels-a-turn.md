# 05: Ctrl-C cancels a turn

**What to build:** Ctrl-C while a turn is running stops that turn, prints `Interrupted.`, and returns to `> ` instead of crashing with a traceback. If the turn was stopped while tool calls were open, each is answered with an "interrupted by the owner" tool message before the next question, so the thread never holds an unanswered tool call. Ctrl-C at an empty `> ` or at `Your decision:` only clears the line (it no longer aborts the process); Ctrl-D or `exit` ends the session. A Write action already running cannot be undone, but it can only be running after the owner approved it.

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] Ctrl-C during a turn prints `Interrupted.` and returns to `> `; the session continues on the same thread
- [ ] Tool calls left open by the cancel are answered "interrupted by the owner" before the next question is processed
- [ ] Ctrl-C at `> ` or at `Your decision:` clears the line and re-prompts
- [ ] Tested through the shared CLI harness (simulated KeyboardInterrupt / cancellation, scripted model)

## Comments
