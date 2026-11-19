# 04: Start Conversations and ask Follow-ups, with live steps

**What to build:** The owner starts a new Conversation from the app, or asks a Follow-up in an open one. The turn runs through the shared driver (`run_conversation`), and its events reach the browser over Server-Sent Events: the turn started, each tool call started and finished or failed, the answer, the turn stopped. Every tab on a thread gets the same events, and a tab that connects mid-turn first gets the current state. One turn at a time per Conversation: input is refused and disabled while a turn runs. Turns on different Conversations run in parallel. Known failures and unexpected errors end the turn with a message in the Conversation, and the server keeps running. Each turn's end writes the run log entry (helper from 01). Each Conversation is one Langfuse trace with the CLI's trace-id rule and `trace_name="web-run"`. A thread started here can be `--resume`d in the CLI.

**Blocked by:** 01, 03

**Status:** ready-for-agent

- [ ] Starting a Conversation creates a new thread and runs its first question; it appears at the top of the list
- [ ] Tool steps arrive live in order, and the answer arrives whole
- [ ] A second question on a thread with a running turn is refused
- [ ] Two Conversations' turns run concurrently (test with a stand-in model that waits)
- [ ] Two SSE clients on one thread receive the same events; a late client gets the current state first
- [ ] A `ClaudeCodeError` or the step limit ends the turn with the CLI's message; an unexpected exception ends the turn, not the server
- [ ] The run log entry is rewritten after each web turn
- [ ] The Langfuse trace id equals the thread id without dashes
- [ ] A Conversation started on the web continues with `python -m agent.cli --resume <id>` (test through the CLI harness)
- [ ] pytest on the Fixture world with the stand-in model; no live calls

Spec: `../spec.md` (Conversations, Live events, Tracing).

## Comments
