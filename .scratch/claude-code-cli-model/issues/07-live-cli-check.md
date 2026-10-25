# 07: Live check against the real Claude Code CLI

**What to build:** One opt-in test that calls the real Claude Code CLI with the production flags. It alerts the maintainer when a Claude Code update breaks the flags, the result shape, the reply contract, or the isolation from the owner's personal setup.

**Blocked by:** 02, 04

**Status:** resolved

- [x] Uses the existing `live` marker, so the default test run skips it
- [x] `claude_code:haiku` with one fake tool and a question that needs two calls of it (for example, the weather in two cities)
- [x] Asserts a valid tool-calls reply with both calls, produced in one CLI turn
- [x] Asserts the context stays small: input plus cache tokens under a few thousand (about 1k on 2026-10-25; about 55k without `--safe-mode`)
- [x] Asserts that token usage and the reported model are present
- [x] The `live` marker's description covers this check
- [x] The default suite passes; the live test passes on the owner's laptop

Traps:
- Keep Haiku. It was the model that failed under `--json-schema`, so as the weaker model it guards the contract best.

Spec: `../spec.md` (Testing Decisions, Live).
