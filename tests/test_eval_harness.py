"""
tests/test_eval_harness.py

The eval harness (ADR-007, trajectory level) with a scripted fake model on two scenarios over
the Fixture world: the graph runs with the Informer and MS365 tools loaded over real MCP, as
`--fixtures` loads them. One scenario's script plays a well-behaved agent and passes; the
other's plays an agent that gets the trajectory wrong. Assertions are on the scenario loader,
the per-run result records, the scores, and the results JSON and report the harness writes.
"""

import json
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage

import agent.graph as graph_module
from agent.evals.__main__ import main
from agent.evals.harness import run_eval, write_results
from agent.evals.records import EvalResults
from agent.evals.scenarios import ScenarioError, load_dataset

DATASET = Path(__file__).parent / "fixtures" / "evals" / "scenarios.json"


# --- scenario format -----------------------------------------------------------------------

def test_dataset_loads_with_its_version_and_scenarios():
    dataset = load_dataset(DATASET)

    assert dataset.format_version == 1
    assert dataset.dataset_version == "test-2026-10-07"
    reply, rejected = dataset.scenarios
    assert reply.id == "reply-flaky-mailbox"
    assert reply.approval == "approve"
    assert reply.inject_failure.server == "ms365"
    assert reply.inject_failure.mode == "transient"
    assert reply.inject_failure.times == 1
    assert rejected.approval == "reject"
    assert rejected.inject_failure is None
    assert rejected.ordering[0].before == "informer_list_overdue_invoices"
    assert rejected.forbidden_tools == ["create_draft_email", "ms365_send-mail"]
    assert rejected.expected_facts == ["Noordzee Advies"]


@pytest.mark.parametrize("change, complaint", [
    ({"format_version": 2}, "unsupported format_version 2"),
    ({"scenarios": [{"id": "x", "input": "hi", "approval": "maybe"}]}, "approval"),
    ({"scenarios": [{"id": "x", "input": "hi", "approval": "approve",
                     "inject_failure": {"server": "informer", "mode": "offline"}}]}, "unknown informer failure mode"),
    ({"scenarios": [{"id": "x", "input": "hi", "approval": "approve", "expected_answer": "typo"}]}, "expected_answer"),
])
def test_invalid_dataset_is_rejected_with_the_reason(tmp_path, change, complaint):
    path = tmp_path / "scenarios.json"
    path.write_text(json.dumps({"format_version": 1, "dataset_version": "v", "scenarios": [], **change}))

    with pytest.raises(ScenarioError, match=complaint):
        load_dataset(path)


# --- running and scoring -------------------------------------------------------------------

QUESTION_ID = "AAMkAGZpeHR1cmUAMESSAGE02"  # Jan de Bakker's question about invoice 2026-031


def _call(name: str, args: dict, call_id: str) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"id": call_id, "name": name, "args": args}])


REMINDER = {"body": {
    "subject": "Payment reminder",
    "body": {"contentType": "text", "content": "Dear client, please pay."},
    "toRecipients": [{"emailAddress": {"address": "facturen@goudenbol.example"}}],
}}

SCRIPTS = {
    # Well behaved: finds the mail (the mailbox fails once and the read is retried), then
    # proposes the reply Draft, which the harness approves.
    "reply-flaky-mailbox": [
        _call("ms365_list-mail-messages", {"search": '"invoice 2026-031"', "select": "id,subject,from"}, "search"),
        _call("ms365_create-reply-draft",
              {"messageId": QUESTION_ID, "body": {"Comment": "Happy to go through the hours on Tuesday."}}, "reply"),
        AIMessage(content="I saved a reply to Jan in your Drafts: you'll go through the hours on Tuesday."),
    ],
    # Gets the trajectory wrong: tries Gmail (forbidden), then drafts a reminder without
    # reading Informer first. The harness rejects both.
    "overdue-reminders-rejected": [
        _call("create_draft_email", {"to": "facturen@goudenbol.example", "subject": "Reminder", "body": "Pay"}, "gmail"),
        _call("ms365_create-draft-email", REMINDER, "draft"),
        AIMessage(content="Understood, I did not save any reminders."),
    ],
}


@pytest.fixture(autouse=True)
def no_backoff_wait(monkeypatch):
    """Keep the retry semantics but skip the real sleeps."""
    monkeypatch.setattr(
        graph_module,
        "TOOL_RETRY_POLICY",
        graph_module.TOOL_RETRY_POLICY._replace(initial_interval=0.0, jitter=False),
    )


@pytest.fixture
def evaluate(scripted_model):
    async def evaluate(scenario_filter: str | None = None):
        return await run_eval(
            load_dataset(DATASET),
            model_name="scripted",
            model_factory=lambda scenario: scripted_model(SCRIPTS[scenario.id]),
            scenario_filter=scenario_filter,
        )
    return evaluate


@pytest.mark.asyncio
async def test_well_behaved_run_passes_and_recovers_from_the_injected_failure(evaluate):
    results = await evaluate("reply-flaky-mailbox")

    [run] = results.runs
    assert run.scenario_id == "reply-flaky-mailbox"
    assert run.model == "scripted"
    assert run.status == "completed"
    assert run.final_answer == "I saved a reply to Jan in your Drafts: you'll go through the hours on Tuesday."
    # The tool outputs are kept per call (the contexts for generation metrics).
    search, reply = run.tool_calls
    assert (search.name, search.status) == ("ms365_list-mail-messages", "success")  # retried past the 503
    assert "Questions about invoice 2026-031" in search.output
    assert (reply.name, reply.status) == ("ms365_create-reply-draft", "success")
    assert [i.decision for i in run.interrupts] == ["approve"]
    assert "ms365_create-reply-draft" in run.interrupts[0].actions
    [draft] = run.drafts
    assert draft["subject"] == "RE: Questions about invoice 2026-031"

    score = run.trajectory
    assert (score.precision, score.recall) == (1.0, 1.0)
    assert score.ordering_met is True
    assert score.forbidden_violations == []
    assert score.recovered is True
    assert score.passed is True
    assert run.answer_facts.missing == []


@pytest.mark.asyncio
async def test_wrong_trajectory_fails_with_the_reasons_scored(evaluate):
    results = await evaluate("overdue-reminders-rejected")

    [run] = results.runs
    assert run.status == "completed"
    assert [(c.name, c.status) for c in run.tool_calls] == [
        ("create_draft_email", "rejected"),
        ("ms365_create-draft-email", "rejected"),
    ]
    assert [i.decision for i in run.interrupts] == ["reject", "reject"]
    assert run.drafts == []  # rejected: nothing reached Outlook

    score = run.trajectory
    assert score.precision == 0.5  # the Gmail call was not required
    assert score.recall == 0.5  # Informer was never read
    assert [(o.before, o.after, o.met) for o in score.ordering] == [
        ("informer_list_overdue_invoices", "ms365_create-draft-email", False),
    ]
    assert score.ordering_met is False
    assert score.forbidden_violations == ["create_draft_email"]
    assert score.recovered is None  # no failure injected
    assert score.passed is False
    assert run.answer_facts.missing == ["Noordzee Advies"]


@pytest.mark.asyncio
async def test_summary_aggregates_both_runs(evaluate):
    results = await evaluate()

    assert [r.scenario_id for r in results.runs] == ["reply-flaky-mailbox", "overdue-reminders-rejected"]
    summary = results.summary
    assert (summary.runs, summary.passed, summary.pass_rate) == (2, 1, 0.5)
    assert summary.mean_precision == 0.75
    assert summary.mean_recall == 0.75
    assert summary.ordering_met_rate == 0.5
    assert summary.forbidden_violations == 1
    assert summary.recovery_rate == 1.0  # the one run with an injected failure recovered
    assert summary.facts_rate == 2 / 3
    assert results.model == "scripted"
    assert results.dataset_version == "test-2026-10-07"


# --- results JSON and report ---------------------------------------------------------------

@pytest.mark.asyncio
async def test_results_json_and_report_are_written_side_by_side(evaluate, tmp_path):
    results = await evaluate()

    json_path, report_path = write_results(results, tmp_path)

    assert json_path.parent == report_path.parent == tmp_path
    assert (json_path.stem, json_path.suffix, report_path.suffix) == (results.eval_run_id, ".json", ".md")
    assert EvalResults.model_validate_json(json_path.read_text()) == results  # re-analysable as written

    report = report_path.read_text()
    assert "Model: `scripted`" in report
    assert "| Passed | 1/2 (50%) |" in report
    assert "| Recovery after injected failure | 100% |" in report
    assert "| reply-flaky-mailbox | PASS |" in report
    assert "| overdue-reminders-rejected | FAIL |" in report
    # A failing run says why.
    assert "missing required tools: informer_list_overdue_invoices" in report
    assert "ordering not met: informer_list_overdue_invoices before ms365_create-draft-email" in report
    assert "forbidden tools called: create_draft_email" in report


# --- the command ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_command_runs_the_chosen_model_on_filtered_scenarios_and_writes_both_files(
        scripted_model, tmp_path, capsys):
    chosen = []

    def create_model(name):
        chosen.append(name)
        return scripted_model(SCRIPTS["reply-flaky-mailbox"])

    await main(["--model", "anthropic:claude-sonnet-5-5", "--dataset", str(DATASET), "--scenario", "reply",
                "--out", str(tmp_path)], create_model=create_model)

    assert chosen == ["anthropic:claude-sonnet-5-5"]
    [json_path] = tmp_path.glob("*.json")
    results = EvalResults.model_validate_json(json_path.read_text())
    assert [r.scenario_id for r in results.runs] == ["reply-flaky-mailbox"]
    assert results.model == "anthropic:claude-sonnet-5-5"
    assert json_path.with_suffix(".md").exists()
    out = capsys.readouterr().out
    assert "1/1 passed" in out
    assert str(json_path) in out


def test_shipped_dataset_loads():
    assert load_dataset().scenarios
