# 01: Upload probe script for Informer v1

**Type:** task

**Model:** Haiku

**Blocked by:** None (can start immediately)

**Status:** resolved

**Closes:** (prerequisite for 02, 16; ADR-012)

**What to build:** A small standalone script the owner runs by hand: given a local file, it sends it to Informer's **v1** purchase-invoice create endpoint with **only the file** (base64, in the `pdf` field) and no invoice details, using the Informer API key and security code from settings and the v1 base address. It prints the exact request (with the file content elided and the credentials masked) and the full response (status, headers, body). It never runs in the test suite and never runs on its own.

- [x] Running it with a path sends exactly one request to v1 and prints request (credentials masked, file elided) and response
- [x] It refuses to run without an explicit confirmation flag, because every run creates a real record in the owner's administration
- [x] It takes the file's type from its content, and has an option to send an image as-is (to learn whether v1 accepts images)
- [x] It is not imported or run by any test; a short usage note sits at its top

## Notes for the implementer

v1 is thinly documented: the spec only lists a base64 `pdf` field and marks no field as required. Do not guess other fields. Never call it from tests or CI.

Spec: `../spec.md`. Decisions: `../findings.md` ("Decisions taken").

## Comments

- 2026-10-22: `scripts/informer_upload_probe.py`. No test imports or runs it (a run creates a real purchase invoice). Checked by hand against a local listener: without `--confirm`, and for an image without `--as-is`, it sends nothing; with `--confirm` it sends one POST to `/v1/invoice/purchase/` whose JSON body is only `pdf`, with the type taken from the bytes. The printed request masks the credentials and elides the file.
