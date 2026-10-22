"""
Upload and mixed-batch eval scenarios: outcome grading from the Fixture world's upload log.

Seam: eval harness on the Fixture world with a scripted model (no live LLM).
"""

from pathlib import Path

import pytest
from langchain_core.messages import AIMessage

import agent.graph as graph_module
from agent.evals.harness import run_eval
from agent.evals.scenarios import DEFAULT_DATASET, Dataset, ExpectedOutcome, Scenario, load_dataset
from agent.evals.outcome import run_passed

DATASET = load_dataset(DEFAULT_DATASET)
MINIMAL_PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
OTHER_PDF = b"%PDF-1.4\nother content\n%%EOF\n"

UPLOAD_IDS = {
    "upload-purchase-approved",
    "upload-purchase-rejected",
    "upload-handover-failure",
    "upload-mixed-vat-rejected",
}


def _upload_scenarios() -> list[Scenario]:
    by_id = {s.id: s for s in DATASET.scenarios}
    missing = UPLOAD_IDS - by_id.keys()
    assert not missing, f"missing upload scenarios: {sorted(missing)}"
    return [by_id[i] for i in sorted(UPLOAD_IDS)]


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


def test_upload_scenarios_declare_expected_outcomes_and_trajectories():
    approved = next(s for s in _upload_scenarios() if s.id == "upload-purchase-approved")
    assert approved.approval == "approve"
    assert approved.expected_outcome == ExpectedOutcome(upload_count=1, upload_file="supplier-march.pdf")
    assert [c.before for c in approved.ordering] == ["informer_check_purchase_invoice"]
    assert approved.ordering[0].after == "informer_upload_purchase_invoice"

    rejected = next(s for s in _upload_scenarios() if s.id == "upload-purchase-rejected")
    assert rejected.approval == "reject"
    assert rejected.expected_outcome == ExpectedOutcome(upload_count=0)

    failure = next(s for s in _upload_scenarios() if s.id == "upload-handover-failure")
    assert failure.expected_outcome == ExpectedOutcome(upload_count=0, require_failure_reported=True)

    mixed = next(s for s in _upload_scenarios() if s.id == "upload-mixed-vat-rejected")
    assert mixed.approval == "reject"
    assert mixed.expected_outcome == ExpectedOutcome(upload_count=0)
    assert "-375.00" in mixed.expected_facts


@pytest.mark.asyncio
async def test_approved_upload_passes_with_exactly_one_matching_file(scripted_model, tmp_path):
    scenario = next(s for s in _upload_scenarios() if s.id == "upload-purchase-approved")
    pdf = tmp_path / "supplier-march.pdf"
    pdf.write_bytes(MINIMAL_PDF)
    path = str(pdf)
    script = [
        _call("informer_check_purchase_invoice", {"path": path}, "check"),
        _call("informer_upload_purchase_invoice", {"path": path}, "upload"),
        _answer("Uploaded supplier-march.pdf for booking."),
    ]
    results = await run_eval(
        Dataset(format_version=1, dataset_version="test", scenarios=[scenario]),
        model_name="scripted",
        model_factory=lambda s: scripted_model(script),
        load_tools=_load_tools_with_downloads(tmp_path),
    )
    [run] = results.runs
    assert run.outcome.passed
    assert run_passed(scenario, run.trajectory, run.outcome, final_answer=run.final_answer)


@pytest.mark.asyncio
async def test_scripted_run_with_right_tools_but_wrong_file_fails_on_outcome(scripted_model, tmp_path):
    scenario = next(s for s in _upload_scenarios() if s.id == "upload-purchase-approved")
    good = tmp_path / "supplier-march.pdf"
    wrong = tmp_path / "other-invoice.pdf"
    good.write_bytes(MINIMAL_PDF)
    wrong.write_bytes(OTHER_PDF)
    script = [
        _call("informer_check_purchase_invoice", {"path": str(good)}, "check"),
        _call("informer_upload_purchase_invoice", {"path": str(wrong)}, "upload"),
        _answer("Uploaded."),
    ]
    results = await run_eval(
        Dataset(format_version=1, dataset_version="test", scenarios=[scenario]),
        model_name="scripted",
        model_factory=lambda s: scripted_model(script),
        load_tools=_load_tools_with_downloads(tmp_path),
    )
    [run] = results.runs
    assert run.trajectory.passed
    assert not run.outcome.passed
    assert not run_passed(scenario, run.trajectory, run.outcome, final_answer=run.final_answer)


def test_rejected_upload_scenario_fails_if_any_upload_was_recorded():
    scenario = next(s for s in _upload_scenarios() if s.id == "upload-purchase-rejected")
    from agent.evals.outcome import score_outcome

    score = score_outcome(scenario, [("supplier-march.pdf", MINIMAL_PDF)], final_answer="")
    assert not score.passed


@pytest.mark.asyncio
async def test_rejected_upload_leaves_no_recorded_upload(scripted_model, tmp_path):
    scenario = next(s for s in _upload_scenarios() if s.id == "upload-purchase-rejected")
    pdf = tmp_path / "supplier-march.pdf"
    pdf.write_bytes(MINIMAL_PDF)
    path = str(pdf)
    script = [
        _call("informer_check_purchase_invoice", {"path": path}, "check"),
        _call("informer_upload_purchase_invoice", {"path": path}, "upload"),
        _answer("I did not upload the file."),
    ]
    results = await run_eval(
        Dataset(format_version=1, dataset_version="test", scenarios=[scenario]),
        model_name="scripted",
        model_factory=lambda s: scripted_model(script),
        load_tools=_load_tools_with_downloads(tmp_path),
    )
    [run] = results.runs
    assert run.outcome.upload_count == 0
    assert run.outcome.passed


@pytest.mark.asyncio
async def test_handover_failure_scenario_fails_when_the_answer_claims_success(scripted_model, tmp_path):
    scenario = next(s for s in _upload_scenarios() if s.id == "upload-handover-failure")
    pdf = tmp_path / "fail-me.pdf"  # matches upload-handover-failure scenario input
    pdf.write_bytes(MINIMAL_PDF)
    path = str(pdf)
    script = [
        _call("informer_check_purchase_invoice", {"path": path}, "check"),
        _call("informer_upload_purchase_invoice", {"path": path}, "upload"),
        _answer("The invoice was uploaded successfully."),
    ]
    results = await run_eval(
        Dataset(format_version=1, dataset_version="test", scenarios=[scenario]),
        model_name="scripted",
        model_factory=lambda s: scripted_model(script),
        load_tools=_load_tools_with_downloads(tmp_path),
    )
    [run] = results.runs
    assert not run.outcome.passed


@pytest.mark.asyncio
async def test_mixed_scenario_passes_only_with_vat_amount_and_no_upload(scripted_model, tmp_path):
    scenario = next(s for s in _upload_scenarios() if s.id == "upload-mixed-vat-rejected")
    pdf = tmp_path / "supplier-march.pdf"
    pdf.write_bytes(MINIMAL_PDF)
    path = str(pdf)
    script = [
        AIMessage(
            content="",
            tool_calls=[
                {"id": "vat", "name": "informer_vat_position", "args": {"year": 2026, "quarter": 3}},
                {"id": "check", "name": "informer_check_purchase_invoice", "args": {"path": path}},
                {"id": "upload", "name": "informer_upload_purchase_invoice", "args": {"path": path}},
            ],
        ),
        _answer("VAT to pay for Q3 2026 is -375.00 EUR. I did not upload the invoice."),
    ]
    results = await run_eval(
        Dataset(format_version=1, dataset_version="test", scenarios=[scenario]),
        model_name="scripted",
        model_factory=lambda s: scripted_model(script),
        load_tools=_load_tools_with_downloads(tmp_path),
    )
    [run] = results.runs
    assert run.outcome.passed
    assert not run.answer_facts.missing
    assert run.passed
    assert run.outcome.upload_count == 0


@pytest.mark.asyncio
async def test_eval_report_shows_outcome_column(scripted_model, tmp_path):
    from agent.evals.harness import run_scenario, write_results

    scenario = next(s for s in _upload_scenarios() if s.id == "upload-purchase-rejected")
    pdf = tmp_path / "supplier-march.pdf"
    pdf.write_bytes(MINIMAL_PDF)
    path = str(pdf)
    run = await run_scenario(
        scenario,
        model=scripted_model([
            _call("informer_check_purchase_invoice", {"path": path}, "check"),
            _call("informer_upload_purchase_invoice", {"path": path}, "upload"),
            _answer("No upload."),
        ]),
        model_name="scripted",
    )
    from agent.evals.records import EvalResults, Summary

    results = EvalResults(
        eval_run_id="test",
        started_at="2026-01-01T00:00:00Z",
        model="scripted",
        prompt_version="v4",
        dataset_path="test",
        dataset_version="test",
        scenario_filter=None,
        runs=[run],
        summary=Summary(runs=1, passed=int(run.passed), pass_rate=float(run.passed), mean_precision=1.0,
                        mean_recall=1.0, ordering_met_rate=1.0, forbidden_violations=0, recovery_rate=None,
                        facts_rate=1.0, mean_outcome_rate=1.0 if run.outcome.passed else 0.0),
    )
    _, report = write_results(results, tmp_path / "out")
    assert "| Outcome |" in report.read_text()


def _load_tools_with_downloads(downloads: Path):
    import os

    from agent.evals.harness import load_fixture_world_tools

    async def loader():
        os.environ["INFORMER_DOWNLOADS_DIR"] = str(downloads)
        os.environ["FIXTURE_WORLD_INFORMER_DOWNLOADS_DIR"] = str(downloads)
        return await load_fixture_world_tools()

    return loader
