# src/agent/evals/efficiency.py
"""Tokens, cost and latency of a scenario run, from the usage the model responses report.

Usage is collected with LangChain's UsageMetadataCallbackHandler, passed in the run's config,
so every model call in the run counts (also calls that later drop out of the message list),
keyed by the model name the provider reported. A response without usage or a model name is
not counted.
"""

from datetime import date
from statistics import mean

from agent.evals.pricing import cost_usd
from agent.evals.records import Efficiency, ModelUsage, RunResult


def efficiency(usage_by_model: dict[str, dict], *, latency_s: float, on: date) -> Efficiency:
    """The run's Efficiency record; costs are priced at the prices in force on `on`."""
    by_model = {
        name: ModelUsage(
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            total_tokens=usage.get("total_tokens", 0),
            cost_usd=cost_usd(name, usage, on=on),
        )
        for name, usage in usage_by_model.items()
    }
    costs = [m.cost_usd for m in by_model.values()]
    return Efficiency(
        latency_s=latency_s,
        input_tokens=sum(m.input_tokens for m in by_model.values()),
        output_tokens=sum(m.output_tokens for m in by_model.values()),
        total_tokens=sum(m.total_tokens for m in by_model.values()),
        cost_usd=None if None in costs else sum(costs),
        by_model=by_model,
    )


def efficiency_totals(runs: list[RunResult]) -> dict:
    """Summary fields: total tokens and cost over the runs, and the mean latency."""
    recorded = [r.efficiency for r in runs if r.efficiency is not None]
    if not recorded:
        return {}
    costs = [e.cost_usd for e in recorded]
    return {
        "total_tokens": sum(e.total_tokens for e in recorded),
        "total_cost_usd": None if None in costs else sum(costs),
        "mean_latency_s": mean(e.latency_s for e in recorded),
    }
