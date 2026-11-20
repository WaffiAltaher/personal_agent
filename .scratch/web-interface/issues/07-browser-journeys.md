# 07: Playwright journeys

**What to build:** A small Playwright suite (Python, `pytest-playwright`) drives the built app against a Fixture-backed server with the stand-in model: log in; start a Conversation and see a tool step then the answer; approve a Write action; two tabs on one Conversation, where answering the Approval in one updates the other and disables its card. The tests are marked so `uv run pytest` skips them when no browser is installed, and say how to install one.

**Blocked by:** 05

**Status:** resolved

- [x] Four journeys pass against `web/dist` built from the current source
- [x] They run on the Fixture world with no live calls
- [x] Without a Playwright browser installed they are skipped with a message naming the install command
- [x] `CLAUDE.md` documents how to run them

Spec: `../spec.md` (Testing Decisions).

## Comments
