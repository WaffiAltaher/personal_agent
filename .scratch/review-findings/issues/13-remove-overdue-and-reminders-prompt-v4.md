# 13: Remove Overdue invoices and Payment reminders; prompt v4

**Type:** task

**Model:** Composer 2.5

**Blocked by:** None (can start immediately)

**Status:** claimed

**Closes:** ADR-012 (drops k54, k55, M56, M57, F7)

**What to build:** Remove everything built on the wrong use of Informer: the overdue-invoice tool, the Payment reminder MCP prompt, the overdue/reminder rules in the system prompt, and the overdue-reminder capstone eval scenarios and their tests. Add prompt version v4 (composed from shared pieces like v3) without those rules, make it the default, and keep v1–v3 unchanged. The Informer server's instructions describe reading accounting data and don't mention uploads; ticket 16 adds an upload sentence that appears only when the upload tools are registered. v4 contains no upload guidance: it lives in the upload tools' own descriptions, so it disappears with them.

- [ ] The overdue-invoice tool and the Payment reminder prompt no longer exist; no test or scenario references them
- [ ] v4 exists, is the default, and contains no Overdue invoice or Payment reminder rule
- [ ] Killing test `k38_released_prompt_versions_never_change` added; v1–v3 fingerprints unchanged; v4's fingerprint added
- [ ] The remaining Informer read tools, the trial balance and the resources are unchanged and their tests pass
- [ ] The eval dataset still loads and validates (with fewer scenarios until tickets 18, 19, 25)

## Notes for the implementer

The glossary and ADR-012 already reflect this. Don't edit v1–v3 text in any way: k38 will fail if you do.

Spec: `../spec.md`. Decisions: `../findings.md` ("Decisions taken").
