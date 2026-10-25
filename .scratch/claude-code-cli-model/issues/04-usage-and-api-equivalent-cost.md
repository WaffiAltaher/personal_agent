# 04: Token usage and API-equivalent cost

**What to build:** The run log and eval reports for a `claude_code:` run show its real token usage and what it would have cost on the API, priced by the model Claude Code actually ran. `claude_code:sonnet` and `claude_code:claude-sonnet-5-5` cost the same, and a model with no price-table row shows no cost rather than a guess.

**Blocked by:** 01

**Status:** resolved

- [x] Every `claude_code:` AI message carries token usage from the CLI's result (input, output, cache read, cache write and thinking), in the shape existing pricing already reads
- [x] Every `claude_code:` AI message records the model the CLI reports it ran
- [x] The run log and eval efficiency price `claude_code:` runs with the reported model, never the alias or the configured name
- [x] The same usage costs the same under `claude_code:sonnet` and `claude_code:claude-sonnet-5-5`
- [x] A reported model without a price-table row has no cost
- [x] The CLI's own cost figure is not used
- [x] Pricing for Gemini and `anthropic:` runs is unchanged
- [x] The whole test suite passes

Traps:
- Today the price lookup takes whatever follows the colon in the configured name. That would price `claude_code:claude-sonnet-5-5` by luck and `claude_code:sonnet` not at all. Fix the lookup, not the table.

Spec: `../spec.md` (Usage and cost).
