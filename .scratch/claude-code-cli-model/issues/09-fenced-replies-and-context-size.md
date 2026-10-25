# 09: Fenced replies are accepted, and the context check sees the real prompt size

**What to build:** A `claude_code:` turn costs one CLI call, not two, and the owner no longer sees "Context above clear threshold" on a short conversation. Found in the owner's first real run (2026-10-25, Langfuse): Sonnet wrapped most replies in ```json fences, each was rejected and re-asked, and the summed usage of both calls (about 121k instead of about 60k) tripped the 100k context threshold on three of four turns.

**Blocked by:** 01, 02, 04

**Status:** resolved

- [x] A reply that is exactly one JSON object inside one Markdown code fence (```json or ```) is accepted like an unfenced one; anything else around it (a stray `<name>…</name>` tag, prose) is still invalid and re-asked
- [x] The context check after a `claude_code:` turn uses the final CLI call's prompt size, not the usage summed across a re-ask; the run log, cost and eval efficiency still count every call
- [x] The bound tools go into the prompt as compact JSON
- [x] Every re-ask logs its reason (the validation error) as a warning
- [x] The live test still passes (run it once)
- [x] The whole test suite passes

Traps:
- ADR-016 and ticket 02 decided fences are malformed. This ticket reverses that for one cleanly fenced object only; record the change in ADR-016.
- The graph reads the prompt size from the message's usage. Don't make the usage smaller to fix the context check, or cost goes wrong; carry the final call's prompt size separately and have the graph prefer it.
- Real-mode tool definitions are about four times larger than the Fixture world's (MS365 draft tools above all), so tests can't reproduce the 60k size. Test the mechanism, not the number.

Spec: `../spec.md` (What comes back; Usage and cost).
