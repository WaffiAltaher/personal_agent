"""
Financial eval scenarios: Revenue and VAT to pay with exact seeded amounts and the right tool.

Seam: eval harness on the Fixture world (scripted model, no live LLM).
"""

import pytest
from langchain_core.messages import AIMessage

import agent.graph as graph_module
from agent.evals.harness import run_eval
from agent.evals.scenarios import DEFAULT_DATASET, Dataset, Scenario, load_dataset
from agent.evals.trajectory import score_facts, score_trajectory

DATASET = load_dataset(DEFAULT_DATASET)
FINANCIAL_IDS = {
    "finance-revenue-q2",
    "finance-vat-q3",
    "finance-revenue-period-range",
    "finance-vat-negative-quarter",
}


def _financial_scenarios() -> list[Scenario]:
    by_id = {s.id: s for s in DATASET.scenarios}
    missing = FINANCIAL_IDS - by_id.keys()
    assert not missing, f"missing financial scenarios: {sorted(missing)}"
    return [by_id[i] for i in sorted(FINANCIAL_IDS)]


TOOL_ARGS = {
    "informer_revenue": {"year": 2026, "period_from": 4, "period_to": 6},
    "informer_vat_position": {"year": 2026, "quarter": 3},
}

SCENARIO_TOOL_ARGS = {
    ("finance-revenue-q2", "informer_revenue"): {"year": 2026, "period_from": 4, "period_to": 6},
    ("finance-vat-q3", "informer_vat_position"): {"year": 2026, "quarter": 3},
    ("finance-revenue-period-range", "informer_revenue"): {"year": 2026, "period_from": 1, "period_to": 2},
    ("finance-vat-negative-quarter", "informer_vat_position"): {"year": 2025, "quarter": 3},
}

# Exact EUR decimal strings from the seeded Fixture world (see tests/informer_server/test_revenue_and_vat.py).
EXPECTED_AMOUNTS = {
    "finance-revenue-q2": "2500.00",
    "finance-vat-q3": "-375.00",
    "finance-revenue-period-range": "1000.00",
    "finance-vat-negative-quarter": "-1000.00",
}


def _script(scenario: Scenario, *, amount_in_answer: str) -> list[AIMessage]:
    tool = scenario.required_tools[0]
    args = SCENARIO_TOOL_ARGS.get((scenario.id, tool), TOOL_ARGS.get(tool, {}))
    return [
        AIMessage(content="", tool_calls=[{"id": "call-0", "name": tool, "args": args}]),
        AIMessage(content=f"The amount is {amount_in_answer} EUR."),
    ]


def _run_passes(scenario: Scenario, run) -> bool:
    return run.trajectory.passed and not run.answer_facts.missing


@pytest.fixture(autouse=True)
def no_backoff_wait(monkeypatch):
    monkeypatch.setattr(
        graph_module,
        "TOOL_RETRY_POLICY",
        graph_module.TOOL_RETRY_POLICY._replace(initial_interval=0.0, jitter=False),
    )


def test_financial_scenarios_use_the_revenue_or_vat_tool_and_exact_amount_facts():
    for scenario in _financial_scenarios():
        assert scenario.workflow == "finance"
        assert scenario.approval == "reject"
        assert len(scenario.required_tools) == 1
        assert scenario.required_tools[0] in {"informer_revenue", "informer_vat_position"}
        assert "informer_trial_balance" in scenario.forbidden_tools
        amount = EXPECTED_AMOUNTS[scenario.id]
        assert amount in scenario.expected_facts


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", _financial_scenarios(), ids=lambda s: s.id)
async def test_scripted_run_with_exact_amount_passes(scenario, scripted_model):
    amount = EXPECTED_AMOUNTS[scenario.id]
    results = await run_eval(
        Dataset(format_version=1, dataset_version="test", scenarios=[scenario]),
        model_name="scripted",
        model_factory=lambda s: scripted_model(_script(s, amount_in_answer=amount)),
    )

    [run] = results.runs
    assert run.status == "completed"
    assert [c.name for c in run.tool_calls] == scenario.required_tools
    assert _run_passes(scenario, run)


@pytest.mark.asyncio
async def test_scripted_run_quoting_a_rounded_amount_fails(scripted_model):
    scenario = next(s for s in _financial_scenarios() if s.id == "finance-revenue-q2")
    results = await run_eval(
        Dataset(format_version=1, dataset_version="test", scenarios=[scenario]),
        model_name="scripted",
        model_factory=lambda s: scripted_model(_script(s, amount_in_answer="2500")),
    )

    [run] = results.runs
    assert run.trajectory.passed
    assert run.answer_facts.missing == ["2500.00"]
    assert not _run_passes(scenario, run)


def test_rounded_amount_without_cents_is_not_treated_as_exact():
    scenario = Scenario(
        id="x",
        input="Revenue?",
        approval="reject",
        expected_facts=["2500.00"],
    )
    assert score_facts(scenario, "Revenue in Q2 was 2500 EUR.").missing == ["2500.00"]
    assert score_facts(scenario, "Revenue in Q2 was 2500.00 EUR.").missing == []
