# 04: Langfuse outage doesn't block the CLI

**Type:** task

**Model:** Haiku

**Blocked by:** None (can start immediately)

**Status:** claimed

**Closes:** E6

**What to build:** When Langfuse can't be reached (refused connection, bad keys, any error from its auth check), the CLI prints a warning naming the Langfuse base URL and runs the agent untraced. Today the auth check raises on everything except one error type, so the warning branch is dead and every run crashes before the agent starts.

- [ ] The connection check never raises: any exception means "not connected" and returns false
- [ ] The warning names the configured Langfuse base URL
- [ ] Test through the CLI driver: with the Langfuse auth check raising a connection error, the run completes and the warning is printed
- [ ] Test: with the auth check raising some other exception (e.g. an HTTP error), same behaviour

## Notes for the implementer

Trap: don't only catch the connection error class from the live traceback; the library raises several kinds. Don't silence the warning or lower its level.

Spec: `../spec.md`. Decisions: `../findings.md` ("Decisions taken").
