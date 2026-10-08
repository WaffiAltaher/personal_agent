# 11: Agent consumes the Informer server

**What to build:** The agent loads Informer tools the same way as MS365 tools: through the shared loader, with an `informer_` prefix, all read-classified. When Informer credentials aren't configured, the agent starts without them and shows a notice. With `--fixtures`, the Informer server runs against the fake Informer API. Demo: "what's outstanding?" is answered from Informer end to end.

**Blocked by:** 03, 04, 09

**Status:** resolved

- [x] Informer tools are bound with the `informer_` prefix and classified as read
- [x] Missing credentials lead to a notice, and the agent still starts
- [x] A seam-A test runs the "what's outstanding?" flow against the Fixture world over real MCP

## Comments

- Done in `agent/tools/informer.py` (`informer_server` / `informer_fixture_server`, registered in `mcp_servers`). Classified by an explicit read allowlist of the six tool names, not by trusting `readOnlyHint`: a tool added to the server later stays a gated Write action until it is listed (ADR-010). New optional agent settings `INFORMER_API_KEY` / `INFORMER_SECURITY_CODE` (this also keeps `Settings` from rejecting them in `.env`); without them the agent starts with the notice "informer tools unavailable: ...".
- Fixture mode: `--fixtures` launches `python -m fixture_world.informer`, which starts the fake Informer API on a free local port inside that same process and runs the real `informer_mcp` server against it through the base-URL override. Chosen over a fake that lives for the CLI session because the adapters spawn a fresh server process per tool call: a self-hosted fake needs no lifecycle in the CLI, and its data is seeded and read-only, so nothing is lost between calls. Informer's "today" is today's weekday moved into the seeded week (`clock.today() - clock.seed_shift()`, i.e. 2026-10-07 with `FIXTURE_WORLD_TODAY=2026-10-07`), because seeded Due dates are fixed.
- Pending on 06: mapping Informer's transient tool-error text ("Transient Informer failure", `informer_mcp.client.TRANSIENT_ERROR_PREFIX`) to a retryable error. 06 had not merged into feat/complete-phases-5-7 when this was done, so it is not wired here and no competing mechanism was built. A test for it will also need a way to inject a failure into the fixture-mode fake (e.g. an env var read by `fixture_world.informer`).
- [x] Resolved by 06: `informer_server` / `informer_fixture_server` set `transient_errors=(re.escape(TRANSIENT_ERROR_PREFIX),)`, so the loader raises a "Transient Informer failure" tool error as `TransientMcpError` and the graph retries it on read tools. Failure injection in fixture mode: `FIXTURE_WORLD_INFORMER_FAILURE=<informer_api.Failure value>` (read by `fixture_world.informer`). Test: `tests/test_mcp_boundary_failures.py::test_transient_informer_failure_is_retried_on_a_read_tool`.
- Tests: `tests/test_fixture_world_informer.py` (seam A: "what's outstanding?" over real MCP; bound names and read class), `tests/test_mcp_loader.py` (missing-credentials notice; a configured server reaches the fake with the credentials).
