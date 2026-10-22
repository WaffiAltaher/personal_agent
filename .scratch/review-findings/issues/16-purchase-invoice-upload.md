# 16: Purchase invoice check and upload tools

**Type:** task

**Model:** Composer 2.5

**Blocked by:** 13

**Status:** ready-for-agent

**Closes:** (ADR-012 as amended; decisions on upload source and safety, Q36, Q37)

**What to build:** Two new tools on the Informer MCP server, for handing a Purchase invoice PDF to Informer:

- `check_purchase_invoice(path)`, a **read**: returns either the refusal reason or the file name, folder and size. Its description tells the model to call it before proposing an upload and to tell the owner what it found.
- `upload_purchase_invoice(path)`, a **Write action** (not on the read allowlist, never retried): re-runs every check, then hands the file's bytes and name to the hand-over transport. It returns a confirmation or an error.

Checks, shared by both tools (one validation, not two copies): extension `.pdf`; the content really is a PDF; size under a cap (a setting, default 2 MB); the resolved path is inside the owner's Downloads folder or a subfolder (no escape through symbolic links or `..`).

The **hand-over transport** is a setting of the Informer server: a small interface taking a file's bytes and name. The Fixture world configures a recording fake that keeps what it receives and can be told to fail. There is **no real transport yet** (a follow-up feature). When no transport is configured, **neither tool is registered** and the server's instructions don't mention uploads. When one is, the instructions add one sentence saying the server accepts Purchase invoice uploads.

There is no v1 client and no v1 fake endpoint: the probe (ticket 02) showed v1 can't take a file alone.

- [ ] Test through the Informer server against the recording fake: an approved upload hands over exactly one file whose bytes and name match
- [ ] Tests: the check refuses, and the upload also refuses, a path outside Downloads, a symbolic link pointing outside, a `..` escape, a wrong extension, a file whose content isn't PDF, and a file over the cap; a refused upload hands nothing over
- [ ] Test: the check reports name, folder and size for a valid file
- [ ] Test: a failure from the fake transport is reported as an error and not retried (handed over at most once)
- [ ] Test: `upload_purchase_invoice` is not on the read allowlist (it pauses for Approval); `check_purchase_invoice` is
- [ ] Test: with no transport configured, neither tool is listed and the server's instructions don't mention uploads
- [ ] The Fixture world configures the recording fake, so the agent can upload in fixtures mode

## Notes for the implementer

Don't add Informer-specific logic to the agent graph or the Approval: both tools are plain MCP tools, and the Approval shows the upload's raw arguments as for any Write action. The transport, size cap and (ticket 17) upload log are Informer server settings. Tests must never touch the real administration.

Spec: `../spec.md`. Decisions: `../findings.md` ("Decisions taken").
