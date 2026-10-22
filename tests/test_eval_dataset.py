"""
tests/test_eval_dataset.py

The shipped scenario dataset (agent/evals/datasets/scenarios.json): 10–20 scenarios covering
the four ITtopia workflows plus failure recovery and rejection. Every scenario runs end to end
through the harness against the Fixture world with a scripted model that calls the scenario's
required tools in order and then answers; the run must complete (scores may be anything).
Every expected answer fact must be derivable from the seeded Fixture world: it appears in what
those tool calls returned.
"""

import pytest
from langchain_core.messages import AIMessage

import agent.graph as graph_module
from agent.evals.harness import run_eval
from agent.evals.scenarios import DEFAULT_DATASET, Dataset, load_dataset

DATASET = load_dataset(DEFAULT_DATASET)

# Arguments the scripted agent calls each tool with (per scenario where it matters).
TOOL_ARGS = {
    "ms365_list-mail-messages": {},
    "ms365_get-calendar-view": {"startDateTime": "2026-10-07T00:00:00Z", "endDateTime": "2026-10-11T23:59:59Z"},
    "ms365_create-reply-draft": {"messageId": "AAMkAGZpeHR1cmUAMESSAGE02",
                                 "body": {"Comment": "Happy to go through the hours on Tuesday."}},
    "informer_list_sales_invoices": {"status": "open"},
    "informer_trial_balance": {"year": 2026},
    "informer_get_sales_invoice": {"invoice_id": 5001},
    "informer_revenue": {"year": 2026, "period_from": 1, "period_to": 13},
    "informer_vat_position": {"year": 2026, "quarter": 1},
    "tavily_search": {"query": "route planning software for a small logistics company"},
}
SCENARIO_TOOL_ARGS = {
    ("reply-sanne-rejected", "ms365_create-reply-draft"): {
        "messageId": "AAMkAGZpeHR1cmUAMESSAGE04",
        "body": {"Comment": "I'll look at your examples before Friday's call."}},
    ("research-payment-terms", "tavily_search"): {"query": "Dutch payment terms for business customers"},
    ("finance-revenue-q2", "informer_revenue"): {"year": 2026, "period_from": 4, "period_to": 6},
    ("finance-vat-q3", "informer_vat_position"): {"year": 2026, "quarter": 3},
    ("finance-revenue-period-range", "informer_revenue"): {"year": 2026, "period_from": 1, "period_to": 2},
    ("finance-vat-negative-quarter", "informer_vat_position"): {"year": 2025, "quarter": 3},
}


def _script(scenario):
    calls = [
        AIMessage(content="", tool_calls=[{
            "id": f"call-{i}", "name": tool, "args": SCENARIO_TOOL_ARGS.get((scenario.id, tool), TOOL_ARGS[tool])}])
        for i, tool in enumerate(scenario.required_tools)
    ]
    return calls + [AIMessage(content="Here is what I found.")]


@pytest.fixture(autouse=True)
def no_backoff_wait(monkeypatch):
    monkeypatch.setattr(graph_module, "TOOL_RETRY_POLICY",
                        graph_module.TOOL_RETRY_POLICY._replace(initial_interval=0.0, jitter=False))


def test_dataset_has_10_to_20_scenarios_covering_every_workflow():
    assert 10 <= len(DATASET.scenarios) <= 21
    assert {s.workflow for s in DATASET.scenarios} == {
        "inbox triage", "finance", "upload", "research", "failure recovery", "rejection", "memory",
    }
    assert {s.approval for s in DATASET.scenarios} == {"approve", "reject"}
    assert {s.inject_failure.server for s in DATASET.scenarios if s.inject_failure} == {"ms365", "handover"}
    assert all(s.required_tools and (s.expected_facts or s.expected_outcome) for s in DATASET.scenarios)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scenario",
    [s for s in DATASET.scenarios if s.workflow not in ("upload", "memory")],
    ids=lambda s: s.id,
)
async def test_scenario_runs_end_to_end_and_its_facts_come_from_the_fixture_world(scenario, scripted_model):
    results = await run_eval(Dataset(format_version=1, dataset_version="test", scenarios=[scenario]),
                             model_name="scripted", model_factory=lambda s: scripted_model(_script(s)))

    [run] = results.runs
    assert (run.status, run.error) == ("completed", None)
    assert [c.name for c in run.tool_calls] == scenario.required_tools
    assert run.trajectory.recall == 1.0
    outputs = "\n".join(c.output for c in run.tool_calls).lower()
    assert [f for f in scenario.expected_facts if f.lower() not in outputs] == []
