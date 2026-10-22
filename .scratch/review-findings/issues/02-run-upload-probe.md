# 02: [manual] Run the upload probe on a PDF

**Type:** manual

**Model:** owner

**Blocked by:** 01

**Status:** resolved

**Closes:** (prerequisite for 16; ADR-012)

**What to build:** The owner runs the probe script on one Purchase invoice that needs booking anyway, as a **PDF** (the owner's Purchase invoices always arrive as PDF, so images are not probed). Record below: the request, the response, and what the accountant sees in Informer (where the record appears, its state, whether the file is attached and viewable, which fields are empty or defaulted, and whether the accountant can complete and book it normally).

- [x] PDF upload recorded: request, response, what the accountant sees
- [x] Conclusion written: does v1 accept a file-only Purchase invoice, and is the result usable by the accountant?
- [x] The record is appended under a `## Probe record` heading in this file

Spec: `../spec.md`. Decisions: `../findings.md` ("Decisions taken").

## Probe record

Run by the owner on 2026-10-22, 15:54 UTC, with `--confirm`, on a real 109,370-byte PDF Purchase invoice from `~/Downloads`.

- Request: `POST https://api.informer.eu/v1/invoice/purchase/`, JSON body `{"pdf": "<base64>"}` only; `Apikey` and `Securitycode` headers.
- Response: **HTTP 200 OK**, body:
  `{"error":{"3000001":"Required field is missing: relation_id","3000004":"Required field is missing: invoice_date","3000013":"Required field is missing: invoice_expiry_date","3000014":"Required field is missing: number","3000015":"Required field is missing: invoice_total","30000":"Required field is missing: lines"}}`
- Rate-limit headers as v2 (`X-RateLimit-Limit: 60`, `X-DailyLimit-Limit: 5000`).

**Conclusion:** v1 does **not** accept a file-only Purchase invoice. It requires `relation_id`, `invoice_date`, `invoice_expiry_date`, `number`, `invoice_total` and `lines`, exactly the bookkeeping the accountant is meant to do. ADR-012's upload premise is false. Also: **v1 reports validation errors with HTTP 200** and an `error` object in the body, so any v1 client must treat an `error` body as a failure whatever the status code. No record should have been created (the owner can confirm in Informer).
