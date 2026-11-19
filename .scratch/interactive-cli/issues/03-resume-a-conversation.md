# 03: Resume a Conversation

**What to build:** The owner can come back to a Conversation in a later session. `--resume <id>` opens the session on that thread instead of a new one; a bare `--resume` opens the most recent Conversation. Everything else is as in 01 (an optional question argument becomes the first turn of this session).

Fixture-world checkpoints move to their own sqlite file under the gitignored checkpoints directory, so each world only ever sees its own Conversations: a bare `--resume` can never reopen a fixtures Conversation against real data, or the reverse.

The run log entry is keyed by the thread id and **replaced** at every exit, so a resumed Conversation stays one entry covering all its sessions. Langfuse already continues the same trace (trace id derived from thread id). ADR-016 says "a CLI `--resume` is a later idea"; amend it to record that it now exists.

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] `--resume <id>` continues that thread: the model sees earlier turns
- [ ] Bare `--resume` picks the most recent Conversation in the current world's checkpoint file
- [ ] An unknown id, or bare `--resume` with no Conversations, stops with a clear message
- [ ] Real and `--fixtures` runs use separate checkpoint files
- [ ] Resuming and exiting replaces the Conversation's run log entry (one entry per thread id, existing entries without a thread id still readable)
- [ ] Usage line and `CLAUDE.md` mention `--resume`
- [ ] ADR-016 amended
- [ ] Tested through the shared CLI harness with a scripted model and a real sqlite checkpointer in a temp dir

## Comments
