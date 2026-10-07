# src/agent/evals/pricing.py
"""What a run cost, from the token usage LangChain reports (`AIMessage.usage_metadata`).

Prices are USD per 1M tokens, dated: each entry holds from `valid_from` until the next entry
for the same model. A model not in the table, or usage the table has no price for (e.g. a
cache write on a model without a cache-write price), has no cost (None), not a guess.

Prices checked on 2026-10-07 against:
- https://ai.google.dev/gemini-api/docs/pricing (Gemini 3.8 Flash, paid tier, standard;
  page last updated 2026-10-07; prices double from 2027-01-01)
- https://platform.claude.com/docs/en/about-claude/pricing (Claude Sonnet 5.5, global
  endpoint, standard speed, no batch)
"""

import re
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Price:
    valid_from: date
    input: float
    output: float  # includes thinking tokens
    cache_read: float | None = None
    cache_write_5m: float | None = None
    cache_write_1h: float | None = None


PRICES: dict[str, list[Price]] = {
    "gemini-3.8-flash": [
        Price(date(2026, 1, 1), input=0.75, output=3.75, cache_read=0.075),
        Price(date(2027, 1, 1), input=1.50, output=7.50, cache_read=0.15),
    ],
    "claude-sonnet-5-5": [
        Price(date(2026, 1, 1), input=2.00, output=10.00, cache_read=0.20, cache_write_5m=2.50, cache_write_1h=4.00),
    ],
}

_DATED_SNAPSHOT = re.compile(r"-\d{8}$")


def _model_key(model_name: str) -> str:
    """`google_genai:gemini-3.8-flash`, `models/gemini-3.8-flash` → `gemini-3.8-flash`;
    a dated snapshot such as `claude-sonnet-5-5-20260915` → `claude-sonnet-5-5`."""
    name = model_name.rpartition(":")[2].removeprefix("models/")
    return _DATED_SNAPSHOT.sub("", name)


def price_on(model_name: str, on: date) -> Price | None:
    """The table price in force for `model_name` on `on`, or None."""
    in_force = [p for p in PRICES.get(_model_key(model_name), []) if p.valid_from <= on]
    return max(in_force, key=lambda p: p.valid_from) if in_force else None


def cost_usd(model_name: str, usage: dict, *, on: date) -> float | None:
    """The cost of `usage` (a LangChain UsageMetadata dict) for `model_name` on date `on`.

    `input_tokens` includes cached input (as both providers' LangChain integrations report it),
    so the cache reads and writes are taken out of it and priced at their own rates."""
    price = price_on(model_name, on)
    if price is None:
        return None
    details = usage.get("input_token_details") or {}
    priced = [  # (tokens, price per 1M)
        (details.get("cache_read") or 0, price.cache_read),
        ((details.get("cache_creation") or 0) + (details.get("ephemeral_5m_input_tokens") or 0),
         price.cache_write_5m),
        (details.get("ephemeral_1h_input_tokens") or 0, price.cache_write_1h),
    ]
    uncached = (usage.get("input_tokens") or 0) - sum(tokens for tokens, _ in priced)
    priced += [(uncached, price.input), (usage.get("output_tokens") or 0, price.output)]
    if any(tokens and rate is None for tokens, rate in priced):
        return None
    return sum(tokens * rate for tokens, rate in priced if tokens) / 1_000_000
