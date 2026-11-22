# 03: E-mail transport in the Informer server

**Type:** task

**What to build:** The real hand-over for Purchase invoices. New Informer settings: `incoming_address`, `invoice_mailbox`, `ms365_package`, `ms365_client_id`, `ms365_tenant_id`, `ms365_expected_username`. A new implementation of `PurchaseInvoiceHandover`, built with the connection to an MS365 server and the two addresses. On `hand_over` it starts that server and calls `send-shared-mailbox-mail` once:
- as the Invoice mailbox, to the Informer incoming address only;
- subject `Purchase invoice: <file name>`, the fixed body "Sent by ITtopia's personal agent.";
- one PDF attachment (base64, `application/pdf`), saved to Sent Items.

Graph's 202 is success, and every error is raised. `python -m informer_mcp` builds it with `npx -y <ms365_package> --org-mode --enabled-tools '^(?:send-shared-mailbox-mail)$'`, with the MS365 IDs in its environment and a working directory outside the repo. It registers the upload tools only when the two addresses, the package and the two IDs are all set. `informer_server()` in `src/agent/tools/informer.py` passes `INFORMER_MS365_PACKAGE` (from `ms365_mcp.PACKAGE`) and the MS365 client ID, tenant ID and expected username. `upload_purchase_invoice`'s message and description say "sent to Informer", not "uploaded" or "booked". The `src/agent/tools/ms365_mcp.py` docstring's "no Mail.Send" is corrected to describe requested scopes, not the token.

**Blocked by:** 02

**Status:** resolved

- [x] Through the Informer server against the stand-in: an approved upload sends exactly one message from the configured Invoice mailbox to the configured Informer incoming address only, with the fixed subject and body and one attachment whose name and bytes match the file (use non-default addresses)
- [x] Reads (`revenue`, `trial_balance`, `check_purchase_invoice`, …) never start the MS365 server
- [x] A login error or transient error from the stand-in is the upload's error, sends at most once, logs nothing, and a login error names the login command
- [x] With any of the required settings missing, neither upload tool is listed and the instructions don't mention uploads
- [x] The existing check, validation and duplicate tests pass with the new transport
- [x] The real entry point's MS365 connection uses the pinned package, `--org-mode`, exactly `send-shared-mailbox-mail` enabled, and a working directory outside the repo
- [x] The agent's Informer server spec carries the pin and the MS365 IDs; no unlisted variable reaches it

Spec: `../spec.md` (Informer server, Agent). ADR-019.

## Comments

- 2026-11-20 (claude): Built `src/informer_mcp/email_handover.py`: `EmailHandover` (a `PurchaseInvoiceHandover` that opens a fresh MS365 session per `hand_over` and calls `send-shared-mailbox-mail` once, Invoice mailbox to Informer incoming address only, fixed subject and body, one base64 PDF, saved to Sent Items; any tool error is raised, a login error with `npx -y <package> --login ...` appended), `email_handover(settings, ms365)` (None unless both addresses, the package and both IDs are set), `ms365_server_parameters` (npx, pinned package, `--org-mode`, `^(?:send-shared-mailbox-mail)$`, temp-dir cwd, environment without `INFORMER_*`/`ENABLED_TOOLS`/inherited `MS365_MCP_*`) and `stdio_connection`. Six new `INFORMER_` settings in `config.py`; `server.main()` wires it. `agent/tools/informer.py` passes `INFORMER_MS365_PACKAGE` (from `ms365_mcp.PACKAGE`) and the client ID, tenant ID and expected username. Upload message and description say "sent to Informer"; `ms365_mcp.py` docstring corrected. The login wording is copied into `informer_mcp` (it can't import `agent`), with a test that keeps it equal to `ms365_mcp.LOGIN`. Tests: `tests/informer_server/test_email_transport.py` (15), two in `test_stdio.py`, one in `test_mcp_loader.py`; `test_purchase_upload.py` now runs on the e-mail transport against the stand-in (`StandInMs365` in the Informer server conftest). `RecordingHandover` stays for `fixture_world.informer` until ticket 04. Suite: 718 passed, 6 deselected.
- 2026-11-20 (claude, review fix): the agent's `Settings` forbade `INFORMER_INCOMING_ADDRESS`/`INFORMER_INVOICE_MAILBOX` in the shared `.env`; it now declares both (unused by the agent). Test: `tests/test_config_paths.py::test_the_informer_email_addresses_in_the_env_file_do_not_stop_the_agent`. Suite: 719 passed, 6 deselected.
