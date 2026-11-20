# 01: Write the run log entry after every turn

**What to build:** The CLI writes a Conversation's run log entry when each turn ends (answered, parked at an Approval and left for a Follow-up, cancelled with Ctrl-C, or stopped by a known failure), not only at exit. The entry is still built from the whole thread and replaces the thread's earlier entry. The questions it lists are rebuilt from the thread's `HumanMessage`s every time. Known failures are kept with the Conversation, so a later write, from another process or a resumed session, keeps errors from earlier turns. The exit write stays as a final pass. The write goes in a helper the web server will call too (ticket 04).

**Blocked by:** None (can start immediately)

**Status:** resolved

- [x] After each turn in a CLI session, the thread's run log entry exists and reflects every turn so far (questions, answers, tools, summed tokens and cost, outcome)
- [x] A turn stopped by a `ClaudeCodeError` or the step limit leaves an entry with that error; a later successful turn in the same Conversation keeps it
- [x] A Conversation resumed in a new process keeps earlier errors in its entry after the next turn
- [x] A Ctrl-C-cancelled turn leaves an entry
- [x] Still exactly one entry per thread; `--fixtures` still writes none
- [x] The helper takes the checkpoint path and thread id and needs no CLI state
- [x] Existing CLI tests pass; new tests use the shared CLI harness with a scripted model
- [x] `CLAUDE.md` and the `cli.py` docstring say the entry is written after every turn

Spec: `../spec.md` (Run log after every turn).

## Comments
