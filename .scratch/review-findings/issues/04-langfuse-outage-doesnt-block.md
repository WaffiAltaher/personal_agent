# 04: Langfuse outage doesn't block the CLI

**Type:** task

**Model:** Haiku

**Blocked by:** None (can start immediately)

**Status:** resolved

**Closes:** E6

**What to build:** When Langfuse can't be reached (refused connection, bad keys, any error from its auth check), the CLI prints a warning naming the Langfuse base URL and runs the agent untraced. Today the auth check raises on everything except one error type, so the warning branch is dead and every run crashes before the agent starts.

- [x] The connection check never raises: any exception means "not connected" and returns false
- [x] The warning names the configured Langfuse base URL
- [x] Test through the CLI driver: with the Langfuse auth check raising a connection error, the run completes and the warning is printed
- [x] Test: with the auth check raising some other exception (e.g. an HTTP error), same behaviour

## Notes for the implementer

Trap: don't only catch the connection error class from the live traceback; the library raises several kinds. Don't silence the warning or lower its level.

Spec: `../spec.md`. Decisions: `../findings.md` ("Decisions taken").

## Comments

- 2026-10-22: `verify_connection` catches every exception and returns false; the CLI warning names `langfuse_base_url`, and a run with Langfuse down gets no callback handler (untraced). New tests in `tests/test_cli_langfuse_outage.py` drive `cli.main()` with refused connection, HTTP error and no-project auth failures, plus a Langfuse-up control. The refused-connection and HTTP-error tests fail if the catch is narrowed to `ConnectionError`.
