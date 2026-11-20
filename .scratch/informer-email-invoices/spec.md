# Spec: Purchase invoices to Informer by e-mail

Status: ready-for-agent

Source: the grilling session of 2026-11-20 (Q1–Q12). Vocabulary follows `GLOSSARY.md` (Purchase invoice, Informer incoming address, Invoice mailbox, Write action, Approval, Fixture world). The decision record is ADR-019, which completes ADR-012's hand-over transport. Decisions also respect ADR-005 (the MS365 server owns the Microsoft login), ADR-010 (classification fails closed) and ADR-011 (the Fixture world is the only test target).

## Problem Statement

The Informer server has `check_purchase_invoice` and `upload_purchase_invoice`, but in real use neither exists: they are registered only when a hand-over transport is configured, and only the Fixture world has one (a recording fake). The owner still forwards each Purchase invoice to Informer by hand.

Informer reads Purchase invoices e-mailed to the administration's incoming address (Scan & Herken: PDF only, 2 MB per attachment, 20 attachments and 20 MB per e-mail). The agent can't send e-mail: the MS365 server exposes only reads and Drafts. The owner's Microsoft login nevertheless carried `Mail.Send`: on 2026-11-20 the pinned server's `send-mail`, started outside the agent, sent a test message as the owner, although the agent never enables that tool.

## Solution

`upload_purchase_invoice` e-mails the checked PDF from the Invoice mailbox (an ITtopia shared mailbox) to the Informer incoming address. The Informer server sends it through its own copy of the pinned MS365 server, started only when an upload needs it, with only `send-shared-mailbox-mail` enabled. That copy shares the owner's one Microsoft login. The sender, the recipient, the subject and the body are fixed by the server; the model passes only the path, as today. An Exchange mail-flow rule rejects mail from the Invoice mailbox to anyone else, and the owner's login carries `Mail.Send.Shared`, not `Mail.Send`.

The Fixture world uses the same e-mail transport against the MS365 stand-in, so tests and evals run the real code path, and evals grade uploads on what the stand-in recorded as sent.

## User Stories

1. As the owner, I want an approved upload to e-mail the PDF to the Informer incoming address, so that Informer reads it and the accountant books it.
2. As the owner, I want it sent from the Invoice mailbox, never from my own address, so that nothing the agent runs sends mail as me.
3. As the owner, I want the recipient fixed by the server and enforced by an Exchange rule, so that no instruction, bug or third-party code can send my invoices or data anywhere else.
4. As the owner, I want one PDF per e-mail with a subject naming the file and a fixed body, so that every e-mail matches one Approval and the model writes nothing that is sent.
5. As the owner, I want each sent e-mail kept in the Invoice mailbox's Sent Items, so that I have a record of every upload.
6. As the owner, I want the answer to say the invoice was sent to Informer, not that it was booked, so that I know what actually happened.
7. As the owner, I want questions about my finances never to depend on Microsoft, so that a Microsoft outage or a dead login doesn't stop them.
8. As the owner, I want a dead Microsoft login reported as that upload's error, naming the login command, and the upload neither retried nor logged as done, so that I can fix it and upload again.
9. As the owner, I want the upload tools present only when both addresses are configured, so that the agent never offers an upload it can't do.
10. As the owner, I want the two addresses kept in `.env` and never committed, so that nobody can put documents into my books from a public repo.
11. As the owner, I want one MS365 package pin for both places that start the server, so that a reviewed bump covers both.
12. As the owner, I want evals to grade uploads on what was actually sent, sender and recipient included, so that a run that e-mails the wrong address fails.
13. As the owner, I want the setup wizard to ask for the two addresses, so that turning on uploads is part of the normal setup.

## Implementation Decisions

### Tenant setup (done by the owner, 2026-11-20)

- The Invoice mailbox, a shared mailbox, with Send As for the owner.
- An Exchange mail-flow rule: mail from the Invoice mailbox to anyone but the Informer incoming address is rejected.
- `Mail.Send` removed from the app's API permissions; `Mail.Send.Shared` added. Removing it from the consent grant and logging in again is assumed done. Whether the token can still send as the owner is open (ticket 07).
- Informer: an incoming address, with Scan & Herken active.

### Informer server

- New settings, with the existing `INFORMER_` prefix:
  - `incoming_address` (the Informer incoming address) and `invoice_mailbox` (the Invoice mailbox), set in `.env` only;
  - `ms365_package`, `ms365_client_id`, `ms365_tenant_id`, `ms365_expected_username`, passed by the agent.
- The upload tools are registered, and the server's instructions mention uploads, only when `incoming_address`, `invoice_mailbox`, `ms365_package`, `ms365_client_id` and `ms365_tenant_id` are all set. Otherwise the server stays read-only, as today with no transport.
- A new e-mail transport implements the existing `PurchaseInvoiceHandover` (`hand_over(file_name, content)`). It is constructed with the connection to an MS365 server and the two addresses:
  - On `hand_over` it starts that server (the agent starts one Informer process per tool call, so this happens per upload, and never for a read) and calls `send-shared-mailbox-mail` once.
  - The call sends as the Invoice mailbox, with the Informer incoming address as the only recipient: no CC or BCC.
  - The subject is `Purchase invoice: <file name>`. The body is one fixed line: "Sent by ITtopia's personal agent."
  - It carries one attachment: the PDF's bytes as base64, `application/pdf`, under its file name. It is saved to Sent Items.
- Graph's 202 is success. Any error, including a login error, is raised to `upload_purchase_invoice`, which reports it, logs nothing and is never retried (it's a Write action). A login error names the login command.
- `upload_purchase_invoice`'s message and description say the invoice was sent to Informer for the accountant to book, not that it was uploaded or booked.
- The real entry point (`python -m informer_mcp`) builds the transport with the real server: `npx -y <ms365_package> --org-mode --enabled-tools '^(?:send-shared-mailbox-mail)$'`, with the MS365 client ID, tenant ID and expected username in its environment and a working directory outside the repo, as the agent's MS365 server has. `--org-mode` is required: without it the pinned server doesn't register work-scoped tools.
- Which MS365 server is started is fixed by the entry point, never by a setting: real for `informer_mcp`, the stand-in for `fixture_world.informer`.

### Agent

- `informer_server()` in `src/agent/tools/informer.py` passes `INFORMER_MS365_PACKAGE` (from `ms365_mcp.PACKAGE`), `INFORMER_MS365_CLIENT_ID`, `INFORMER_MS365_TENANT_ID` and `INFORMER_MS365_EXPECTED_USERNAME` (from the agent's MS365 settings) to the Informer server. Nothing else changes in the agent: the upload is still a plain Write action showing its raw arguments in the Approval.
- The agent's own MS365 server is unchanged. Its docstring's "no Mail.Send" is corrected: it describes the scopes the server requests, not what the token may carry.

### Fixture world and evals

- The MS365 stand-in gains `send-shared-mailbox-mail`, with the real tool's argument shape at the pinned version. It records every call (sender, recipients, CC, BCC, subject, body, attachments) as a JSON line in a file named by a `FIXTURE_WORLD_MS365_*` variable, read back with a helper, as Drafts are. Its existing failure modes apply to it, plus a switch that fails only the send.
- `fixture_world.informer` builds the e-mail transport against the stand-in, with made-up addresses.
- `RecordingHandover`, its log and `read_upload_log` are removed. The upload outcome grade reads the stand-in's sent log and requires the configured sender and recipient. The upload-failure scenario uses the stand-in's send failure switch.

### Setup and docs

- The setup wizard gains an optional Informer step asking for the two addresses and writing them to `.env`.
- `CLAUDE.md` documents the new settings.

## Testing Decisions

- No test reaches Microsoft or Informer (ADR-011); the e-mail transport runs only against the stand-in. No live model calls (the owner's quota rule).
- Through the Informer server over an in-memory MCP session, with the stand-in:
  - an approved upload sends exactly one message, from the configured Invoice mailbox, to the configured Informer incoming address only (no CC or BCC), with the fixed subject and body and one attachment whose name and bytes match the file;
  - reads never start the stand-in;
  - a stand-in login error or transient error is reported as the upload's error, sends at most once, and logs nothing;
  - with either address missing, neither upload tool is listed and the instructions don't mention uploads.
  
  Use non-default addresses, so that a hard-coded address fails.
- Existing check and validation tests (path, type, size, duplicates) keep passing against the new transport.
- The agent's Informer server spec carries the MS365 pin, client ID and tenant ID; the loader's existing environment-allowlist tests cover the rest.
- Evals: the existing upload scenarios (approve, reject, failure reported, mixed step) keep their meaning and are graded on the stand-in's sent log.

## Out of Scope

- Getting Purchase invoices from e-mail attachments or vendors' websites (the upload still takes a local file).
- Waiting for or parsing bounces. A rejected or undelivered message shows only in the Invoice mailbox.
- More than one invoice per e-mail.
- Sending from the owner's own mailbox, and sending anything other than Purchase invoices.
- PDFs over 2 MB (Graph's inline attachment limit is about 3 MB, and Informer's 2 MB per attachment).

## Further Notes

- Informer's settings (incoming address, Scan & Herken, the optional Informer Inbox) are documented in the Informer help centre: "How can I set up the incoming email?" (helpdesk.informer.nl, article 6731706).
- When bumping the MS365 pin, also review `send-shared-mailbox-mail`'s argument shape and whether it still needs `--org-mode`.
