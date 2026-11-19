# 02: The Approval prompt accepts a Follow-up

**What to build:** At the `Your decision:` prompt the owner can answer `approve` or `reject` as today, or type a Follow-up instead. A Follow-up there rejects the pending Write actions as "moved on" (the conversation driver already does this when a new user message arrives on a thread paused for Approval, see the **Approval** entry in `GLOSSARY.md` and the ADR-010 amendment of 2026-10-22) and is then answered as the next turn. To guard against typos, a single word that is neither `approve` nor `reject` (e.g. `aprove`) is not taken as a Follow-up: the owner is asked again. The prompt text says a follow-up question rejects.

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] `approve` / `reject` (case-insensitive, trimmed) behave as today
- [ ] Input of more than one word is a Follow-up: pending Write actions are answered as rejected ("moved on"), none of them runs, and the Follow-up is answered
- [ ] A single unrecognised word re-prompts and rejects nothing
- [ ] The prompt tells the owner a follow-up question rejects
- [ ] The run log outcome of a Conversation with a moved-on Approval is consistent with an explicit reject
- [ ] Tested through the shared CLI harness with a scripted model

## Comments
