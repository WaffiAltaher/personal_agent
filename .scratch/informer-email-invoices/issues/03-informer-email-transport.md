# 03: E-mail transport in the Informer server

**Type:** task

**What to build:** The real hand-over for Purchase invoices. New Informer settings: `incoming_address`, `invoice_mailbox`, `ms365_package`, `ms365_client_id`, `ms365_tenant_id`, `ms365_expected_username`. A new implementation of `PurchaseInvoiceHandover`, built with the connection to an MS365 server and the two addresses. On `hand_over` it starts that server and calls `send-shared-mailbox-mail` once:
- as the Invoice mailbox, to the Informer incoming address only;
- subject `Purchase invoice: <file name>`, the fixed body "Sent by ITtopia's personal agent.";
- one PDF attachment (base64, `application/pdf`), saved to Sent Items.

Graph's 202 is success, and every error is raised. `python -m informer_mcp` builds it with `npx -y <ms365_package> --org-mode --enabled-tools '^(?:send-shared-mailbox-mail)$'`, with the MS365 IDs in its environment and a working directory outside the repo. It registers the upload tools only when the two addresses, the package and the two IDs are all set. `informer_server()` in `src/agent/tools/informer.py` passes `INFORMER_MS365_PACKAGE` (from `ms365_mcp.PACKAGE`) and the MS365 client ID, tenant ID and expected username. `upload_purchase_invoice`'s message and description say "sent to Informer", not "uploaded" or "booked". The `src/agent/tools/ms365_mcp.py` docstring's "no Mail.Send" is corrected to describe requested scopes, not the token.

**Blocked by:** 02

**Status:** ready-for-agent

- [ ] Through the Informer server against the stand-in: an approved upload sends exactly one message from the configured Invoice mailbox to the configured Informer incoming address only, with the fixed subject and body and one attachment whose name and bytes match the file (use non-default addresses)
- [ ] Reads (`revenue`, `trial_balance`, `check_purchase_invoice`, …) never start the MS365 server
- [ ] A login error or transient error from the stand-in is the upload's error, sends at most once, logs nothing, and a login error names the login command
- [ ] With any of the required settings missing, neither upload tool is listed and the instructions don't mention uploads
- [ ] The existing check, validation and duplicate tests pass with the new transport
- [ ] The real entry point's MS365 connection uses the pinned package, `--org-mode`, exactly `send-shared-mailbox-mail` enabled, and a working directory outside the repo
- [ ] The agent's Informer server spec carries the pin and the MS365 IDs; no unlisted variable reaches it

Spec: `../spec.md` (Informer server, Agent). ADR-019.

## Comments
