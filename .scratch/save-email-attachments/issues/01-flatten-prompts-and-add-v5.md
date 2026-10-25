# 01: Flatten every prompt version to full text, and add v5 as the default

**What to build:** Every prompt version holds its own full text instead of being built by concatenating an earlier version, so a future version is a copy-and-edit. A new version `v5` names `~/Downloads/personal_agent` as the agent's folder and becomes the default. The owner sees no change except that line in the prompt.

**Blocked by:** None (can start immediately)

**Status:** resolved

- [x] V3 and V4 are written out as complete strings; neither references another prompt constant
- [x] V3 and V4 are byte-for-byte unchanged: their existing lines in the released-prompt hash test pass untouched (never edit an existing hash line)
- [x] `v5` is V4's full text with exactly one change: the default data folder line names `/Users/waffi/Downloads/personal_agent` instead of `/Users/waffi/Downloads/Personal`
- [x] `v5` is in the prompt registry and has its own new hash line in the released-prompt test
- [x] The default prompt version setting is `v5`
- [x] The whole test suite passes

Traps:
- V4 is currently V2 plus extra text, **not** V3 plus extra text. Flatten what the code actually does; if you change V4's content to include V3's rules, its hash test fails, which is the point of that test.
- Don't fix wording, whitespace or the "Overdue invoice" rules left in V3 while flattening. Any byte change breaks the hash.

Spec: `../spec.md` (Prompts).
