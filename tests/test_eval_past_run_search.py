"""
Past-run search eval scenarios: agent-written FTS terms and retry when the first search is empty.

Seam: eval harness on the Fixture world with a scripted model (no live LLM).
"""

from datetime import timedelta

import pytest
from langchain_core.messages import AIMessage

import agent.graph as graph_module
from agent.evals.harness import run_eval
from agent.evals.scenarios import DEFAULT_DATASET, Dataset, Scenario, load_dataset
from fixture_world import clock

DATASET = load_dataset(DEFAULT_DATASET)
PAST_RUN_IDS = {"memory-vat-last-week", "memory-search-retry"}


def _past_run_scenarios() -> list[Scenario]:
    by_id = {s.id: s for s in DATASET.scenarios}
    missing = PAST_RUN_IDS - by_id.keys()
    assert not missing, f"missing past-run scenarios: {sorted(missing)}"
    return [by_id[i] for i in sorted(PAST_RUN_IDS)]


@pytest.fixture(autouse=True)
def no_backoff_wait(monkeypatch):
    monkeypatch.setattr(
        graph_module,
        "TOOL_RETRY_POLICY",
        graph_module.TOOL_RETRY_POLICY._replace(initial_interval=0.0, jitter=False),
    )


def _call(name: str, args: dict, call_id: str) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"id": call_id, "name": name, "args": args}])


def _answer(text: str) -> AIMessage:
    return AIMessage(content=text)


def test_past_run_scenarios_are_in_the_dataset():
    for scenario in _past_run_scenarios():
        assert scenario.workflow == "memory"
        assert scenario.approval == "reject"
        assert scenario.required_tools == ["retrieve_episodic_memory"]


@pytest.mark.asyncio
async def test_vat_last_week_scenario_passes_with_scripted_search(scripted_model):
    scenario = next(s for s in _past_run_scenarios() if s.id == "memory-vat-last-week")
    today = clock.today()
    since = (today - timedelta(days=7)).isoformat()
    until = (today - timedelta(days=1)).isoformat()
    script = [
        _call(
            "retrieve_episodic_memory",
            {"terms": "VAT", "since": since, "until": until},
            "mem-1",
        ),
        _answer("Last week you asked how much VAT you owe for Q3 2026."),
    ]
    results = await run_eval(
        Dataset(format_version=1, dataset_version="test", scenarios=[scenario]),
        model_name="scripted",
        model_factory=lambda s: scripted_model(script),
    )
    [run] = results.runs
    assert run.status == "completed"
    assert run.trajectory.passed
    assert not run.answer_facts.missing


@pytest.mark.asyncio
async def test_retry_scenario_calls_search_twice_when_the_first_is_empty(scripted_model):
    scenario = next(s for s in _past_run_scenarios() if s.id == "memory-search-retry")
    script = [
        _call("retrieve_episodic_memory", {"terms": "October payroll"}, "mem-1"),
        _call("retrieve_episodic_memory", {"terms": "25th"}, "mem-2"),
        _answer("You asked when the salary payment date is — your October payroll question."),
    ]
    results = await run_eval(
        Dataset(format_version=1, dataset_version="test", scenarios=[scenario]),
        model_name="scripted",
        model_factory=lambda s: scripted_model(script),
    )
    [run] = results.runs
    assert run.status == "completed"
    assert run.trajectory.passed
    assert [c.name for c in run.tool_calls].count("retrieve_episodic_memory") == 2
    assert run.tool_calls[0].output == "No matching runs found in episodic memory."
    assert "25th" in run.tool_calls[1].output.lower()
