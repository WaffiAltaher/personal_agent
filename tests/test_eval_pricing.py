"""
tests/test_eval_pricing.py

Cost of a run from the token usage LangChain reports (`AIMessage.usage_metadata`), priced with
the dated per-model table in agent.evals.pricing. Expected values are worked by hand from the
published prices (Gemini 3.8 Flash: $0.75 in / $3.75 out / $0.075 cached per 1M tokens through
2026-12-31, then double; Claude Sonnet 5.5: $2 in / $10 out / $0.20 cache hit / $2.50 5-minute
cache write per 1M tokens).
"""

from datetime import date

import pytest

from agent.evals.pricing import cost_usd

GEMINI_USAGE = {
    "input_tokens": 1_000_000,
    "output_tokens": 100_000,
    "total_tokens": 1_100_000,
    "input_token_details": {"cache_read": 200_000},
}


def test_gemini_cost_counts_cached_input_at_the_cache_price():
    # 800k uncached × 0.75 + 200k cached × 0.075 + 100k out × 3.75, per 1M
    assert cost_usd("gemini-3.8-flash", GEMINI_USAGE, on=date(2026, 10, 7)) == pytest.approx(0.99)


def test_price_is_the_one_in_force_on_the_run_date():
    # From 2027-01-01 the Gemini 3.8 Flash prices double.
    assert cost_usd("gemini-3.8-flash", GEMINI_USAGE, on=date(2027, 1, 2)) == pytest.approx(1.98)


def test_claude_cost_prices_cache_reads_and_writes():
    usage = {
        "input_tokens": 10_000,  # includes the cache read and the cache write
        "output_tokens": 2_000,
        "total_tokens": 12_000,
        "input_token_details": {"cache_read": 4_000, "cache_creation": 0, "ephemeral_5m_input_tokens": 1_000},
    }
    # 5k uncached × 2 + 4k read × 0.20 + 1k written × 2.50 + 2k out × 10, per 1M
    assert cost_usd("claude-sonnet-5-5", usage, on=date(2026, 10, 7)) == pytest.approx(0.0333)


@pytest.mark.parametrize("name", ["google_genai:gemini-3.8-flash", "models/gemini-3.8-flash"])
def test_provider_prefixes_are_ignored(name):
    assert cost_usd(name, GEMINI_USAGE, on=date(2026, 10, 7)) == pytest.approx(0.99)


def test_a_dated_snapshot_name_is_priced_as_its_model():
    usage = {"input_tokens": 1_000_000, "output_tokens": 0, "total_tokens": 1_000_000}
    assert cost_usd("claude-sonnet-5-5-20260915", usage, on=date(2026, 10, 7)) == pytest.approx(2.0)


def test_unknown_model_has_no_cost_rather_than_a_guess():
    assert cost_usd("gpt-9", GEMINI_USAGE, on=date(2026, 10, 7)) is None


def test_usage_the_table_cannot_price_has_no_cost():
    # Gemini has no cache-write price in the table: a write cannot be priced.
    usage = {**GEMINI_USAGE, "input_token_details": {"cache_creation": 10}}
    assert cost_usd("gemini-3.8-flash", usage, on=date(2026, 10, 7)) is None
