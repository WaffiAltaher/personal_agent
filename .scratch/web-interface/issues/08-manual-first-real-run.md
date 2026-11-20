# 08: Owner's first real run

**What to build:** The owner sets a password, builds the app, starts `python -m agent.web` against real data, and checks the feature end to end. Findings become new tickets.

**Blocked by:** 05, 06

**Status:** ready-for-human

- [ ] Log in; a CLI-started Conversation is in the list and continues in the browser
- [ ] A new Conversation with a multi-tool question shows live steps and an answer
- [ ] A Write action (e.g. a Draft) is approved from the card; another is rejected by a Follow-up
- [ ] Two Conversations run at once; one is open in two tabs
- [ ] Stop cancels a running turn
- [ ] The status strip matches the real logins
- [ ] A web-started Conversation continues with `python -m agent.cli --resume <id>`
- [ ] Langfuse shows one trace per Conversation

Spec: `../spec.md`.

## Comments
