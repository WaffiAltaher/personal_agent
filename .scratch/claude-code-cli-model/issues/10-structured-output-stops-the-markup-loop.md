# 10: The reply comes through --json-schema, so Claude can't loop on tool-call markup

**What to build:** A `claude_code:` turn with tool history answers instead of hanging until the 180 s timeout. Found in the owner's run of 2026-10-28 (Langfuse trace 79b14cd6): the second turn of "did I ever have contact with Alfie Denwood?" never answered. Replays of that turn showed why: with no real tool in the request (`--tools ""`), Sonnet started a native tool call, wrote it out as text (`<invoke name="x"></invoke>`), and in about 45% of replays repeated it until killed (784 repeats in 200 s). `--json-schema` gives the model one real tool, StructuredOutput, and the markup stopped (3 of 3 replays).

**Blocked by:** 02, 09

**Status:** resolved

- [x] With tools bound, the reply contract goes to the CLI as `--json-schema`, naming only the bound tools
- [x] The reply is read from the CLI's `structured_output`, not its result text; the fence and leading-text handling of ticket 09 is gone
- [x] Tool calls after refused native attempts (more than 2 CLI turns) are accepted without a re-ask
- [x] An answer after refused native attempts is re-asked: it may be the believable wrong answer ADR-016 feared
- [x] The context check uses the prompt size of the call's last request to Claude (the final `usage.iterations` entry), not `usage` summed over the refused attempts; without `iterations` it falls back to `usage`. Found in the owner's run of 2026-10-29: a false "Context above clear threshold (105649 tokens)" on a ~53k prompt
- [x] The live test still passes (run it once)
- [x] The whole test suite passes

Traps:
- ADR-016 rejected `--json-schema`; record the reversal and its evidence there.
- A clean StructuredOutput reply is 2 CLI turns, not 1 (Claude Code 2.1.312): the old "more than 1 turn" rule would reject every reply.
- One CLI call can make several requests to Claude. `usage` sums them; `iterations` holds only the last (Claude Code 2.1.312, undocumented). Cost keeps the sum.
- Don't replay real-mode turns in loops to measure: each is ~52k tokens of the owner's subscription.

Spec: `../spec.md` (What comes back).

## Comments

- 2026-10-29, the owner's real run after the fix: no hang and no context warning. The first call made 3 refused native attempts and then answered "I couldn't search for Alfie Denwood…"; the guard re-asked, and the re-ask returned `retrieve_episodic_memory`. Summed usage was 157,543 against a 52,854-token last request.
