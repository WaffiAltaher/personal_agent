# 06: Login status strip and recovery without a restart

**What to build:** The app shows a status strip for Google, Claude Code (when a `claude_code:` model is configured), MS365 and Informer: alive or dead, and for a dead one, its login command. The checks are cached and refreshed at the start of every turn with a short timeout, so a turn is never held up for long. Status changes go out on the event stream. An MCP server skipped at startup for a login problem is loaded again once its check passes, and later turns get its tools. A running turn keeps its tools.

**Blocked by:** 04

**Status:** resolved

- [x] The strip shows each integration's state after login
- [x] A Google token that dies while the server runs shows as dead with `python -m agent.auth.google`; a fresh token shows alive on the next turn
- [x] An MS365 server skipped at startup is loaded on the next turn after its login passes, and its tools are bound from then on
- [x] A slow or hanging check doesn't block a turn beyond the timeout
- [x] pytest uses Fixture-world stand-ins for the checks; no live logins

Spec: `../spec.md` (Login status).

## Comments
