# 01: Follow-ups in one session

**What to build:** The CLI becomes a session. `python -m agent.cli [--fixtures] [--debug] ["first question"]` starts the agent once (model, login checks, tools, MCP servers) and then reads lines at a `> ` prompt. Each line is a Follow-up on the same thread (see **Conversation** and **Follow-up** in `GLOSSARY.md`), sent through the existing conversation driver, which already supports several user messages on one thread. The question argument is optional: when given, it runs as the first turn before the first prompt. Approvals inside a turn work as today.

At exit the run log (episodic memory) gets **one entry for the whole Conversation**, not one per turn: every question and answer, every tool called, the total tokens and cost, and the outcome. This matches Langfuse, where the Conversation is already one trace (trace id derived from the thread id). A Fixture-world Conversation stays out of real memory, as today.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] With no question argument the CLI goes straight to `> `; with one, it answers it first and then prompts
- [ ] Each line at `> ` is answered with everything said earlier in the Conversation available to the model
- [ ] An empty line does nothing; `exit`, `quit` and Ctrl-D (EOF) end the session
- [ ] `Conversation <thread id>` is printed at start and at exit
- [ ] `--debug` prints, after each turn, only the messages that turn added
- [ ] At exit, exactly one run log entry covers the whole Conversation: all questions and answers, all tools, summed tokens and cost, outcome; not written for `--fixtures`
- [ ] The CLI tests drive the session through a stubbed line reader added to the shared CLI test harness (scripted model, no live calls); existing CLI tests still pass
- [ ] `CLAUDE.md`'s run command and the CLI module docstring describe the session

## Comments
