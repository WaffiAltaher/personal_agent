"""
Invoice archive eval scenarios (ADR-020): Process, a lone Upload to OneDrive, the Processed check
and name clashes, graded from what the Fixture world's stand-ins hold after the run (the sent
Informer uploads and the files added to the drive).

Seams: `score_outcome` for the archive grade, and the eval harness on the Fixture world with a
scripted model (no live LLM) for the scenarios.
"""

from importlib.resources import files

import pytest
from langchain_core.messages import AIMessage

import agent.graph as graph_module
from agent.evals.harness import EVAL_DOWNLOAD_PDFS, run_scenario
from agent.evals.outcome import run_passed, score_outcome
from agent.evals.scenarios import DEFAULT_DATASET, ExpectedOutcome, FailureInjection, Scenario, load_dataset

DATASET = load_dataset(DEFAULT_DATASET)
BY_ID = {s.id: s for s in DATASET.scenarios}
ADMIN = "Documents/ittopia/admin"
OCTOBER = f"{ADMIN}/2026/October"
SEEDED_DRIVE = files("fixture_world") / "data" / "ms365" / "drive"

ARCHIVE_IDS = {
    "process-approved",
    "onedrive-only-asks-process",
    "onedrive-only-informer-done",
    "processed-check-by-file",
    "processed-list-by-month",
    "onedrive-name-clash-same-contents",
    "onedrive-name-clash-different-contents",
    "onedrive-scanned-pdf-asks-date",
    "process-drive-failure",
}


def _scenario(**expected) -> Scenario:
    return Scenario(id="s", input="Process hosting-2026-10.pdf.", approval="approve",
                    expected_outcome=ExpectedOutcome(upload_count=0, **expected))


# --- the archive grade ---------------------------------------------------------------------------

def test_the_archive_grade_passes_the_expected_files_with_their_bytes():
    scenario = _scenario(archived_files={f"{OCTOBER}/hosting-2026-10.pdf": "hosting-2026-10.pdf"})
    pdf = EVAL_DOWNLOAD_PDFS["hosting-2026-10.pdf"]

    score = score_outcome(scenario, [], final_answer="", archived={f"{OCTOBER}/hosting-2026-10.pdf": pdf},
                          expected_archive={f"{OCTOBER}/hosting-2026-10.pdf": pdf})

    assert score.passed, score.detail
    assert score.archived_files == [f"{OCTOBER}/hosting-2026-10.pdf"]


def test_the_archive_grade_fails_the_wrong_month_an_extra_file_and_other_bytes():
    want = f"{OCTOBER}/hosting-2026-10.pdf"
    scenario = _scenario(archived_files={want: "hosting-2026-10.pdf"})
    pdf = EVAL_DOWNLOAD_PDFS["hosting-2026-10.pdf"]

    def grade(archived: dict[str, bytes]) -> bool:
        return score_outcome(scenario, [], final_answer="", archived=archived,
                             expected_archive={want: pdf}).passed

    assert not grade({f"{ADMIN}/2026/September/hosting-2026-10.pdf": pdf})
    assert not grade({want: pdf, f"{OCTOBER}/extra.pdf": pdf})
    assert not grade({want: b"%PDF-1.4 other"})
    assert not grade({})


def test_an_empty_archive_expectation_fails_any_added_file():
    scenario = _scenario(archived_files={})

    assert score_outcome(scenario, [], final_answer="", archived={}).passed
    assert not score_outcome(scenario, [], final_answer="", archived={f"{OCTOBER}/x.pdf": b"%PDF-"}).passed


def test_without_an_archive_expectation_added_files_are_not_graded():
    scenario = _scenario()

    assert score_outcome(scenario, [], final_answer="", archived={f"{OCTOBER}/x.pdf": b"%PDF-"}).passed


def test_a_drive_failure_is_transient_only_and_takes_no_times():
    assert FailureInjection(server="drive", mode="transient").server == "drive"
    with pytest.raises(ValueError):
        FailureInjection(server="drive", mode="auth")
    with pytest.raises(ValueError):
        FailureInjection(server="drive", mode="transient", times=1)


# --- the scenarios, run with a scripted model ------------------------------------------------------

@pytest.fixture(autouse=True)
def no_backoff_wait(monkeypatch):
    monkeypatch.setattr(graph_module, "TOOL_RETRY_POLICY",
                        graph_module.TOOL_RETRY_POLICY._replace(initial_interval=0.0, jitter=False))


def _calls(*calls: tuple[str, dict]) -> AIMessage:
    """One model turn proposing `calls` (tool name, arguments) together."""
    return AIMessage(content="", tool_calls=[
        {"id": f"{name}-{i}", "name": name, "args": args} for i, (name, args) in enumerate(calls)])


def _answer(text: str) -> AIMessage:
    return AIMessage(content=text)


HOSTING = "hosting-2026-10.pdf"
HOSTING_TARGET = f"{OCTOBER}/{HOSTING}"
KPN = "kpn-factuur-123456.pdf"
KPN_RENAMED = f"{OCTOBER}/kpn-factuur-123456 1.pdf"


def _process(name: str, invoice_date: str, target: str, *, status: str) -> list[AIMessage]:
    """The right Process of `name`: the date, both checks, both uploads under one Approval."""
    return [
        _calls(("read_pdf_text", {"path": name})),
        _calls(("informer_check_purchase_invoice", {"path": name}),
               ("ms365_check_invoice_archive", {"path": name, "invoice_date": invoice_date})),
        _calls(("informer_upload_purchase_invoice", {"path": name}),
               ("ms365_upload_to_onedrive", {"path": name, "invoice_date": invoice_date, "target_path": target})),
        _answer(status),
    ]


RIGHT_SCRIPTS = {
    "process-approved": _process(
        HOSTING, "2026-10-05", HOSTING_TARGET,
        status=f"Processed. Uploaded to Informer: yes (2026-10-07) · Uploaded to OneDrive: yes ({HOSTING_TARGET})"),
    "onedrive-only-asks-process": [
        _calls(("informer_check_purchase_invoice", {"path": HOSTING})),
        _answer("hosting-2026-10.pdf is not uploaded to Informer yet. Process instead?\n"
                "Uploaded to Informer: no · Uploaded to OneDrive: no"),
    ],
    "onedrive-only-informer-done": [
        _calls(("read_pdf_text", {"path": HOSTING})),
        _calls(("informer_check_purchase_invoice", {"path": HOSTING}),
               ("ms365_check_invoice_archive", {"path": HOSTING, "invoice_date": "2026-10-05"})),
        _calls(("ms365_upload_to_onedrive", {"path": HOSTING, "invoice_date": "2026-10-05",
                                             "target_path": HOSTING_TARGET})),
        _answer(f"Uploaded to Informer: yes (2026-10-06) · Uploaded to OneDrive: yes ({HOSTING_TARGET})"),
    ],
    "processed-check-by-file": [
        _calls(("read_pdf_text", {"path": "kpn-oktober.pdf"})),
        _calls(("ms365_check_invoice_archive", {"path": "kpn-oktober.pdf", "invoice_date": "2026-10-02"})),
        _answer(f"Yes, it is in the archive as kpn-factuur-123456.pdf.\n"
                f"Uploaded to Informer: no · Uploaded to OneDrive: yes ({OCTOBER}/kpn-factuur-123456.pdf)"),
    ],
    "processed-list-by-month": [
        _calls(("ms365_list_invoice_archive", {"year": 2026, "month": 10})),
        _answer(f"October 2026 holds CH-2026-1044.pdf.\nUploaded to Informer: no · Uploaded to OneDrive: "
                f"yes ({OCTOBER}/CH-2026-1044.pdf), matched names only"),
    ],
    "onedrive-name-clash-same-contents": [
        _calls(("read_pdf_text", {"path": "Factuur.pdf"})),
        _calls(("informer_check_purchase_invoice", {"path": "Factuur.pdf"}),
               ("ms365_check_invoice_archive", {"path": "Factuur.pdf", "invoice_date": "2026-09-17"})),
        _answer(f"Factuur.pdf is already in the archive; nothing to upload.\nUploaded to Informer: yes "
                f"(2026-09-20) · Uploaded to OneDrive: yes ({ADMIN}/2026/September/Factuur.pdf)"),
    ],
    "onedrive-name-clash-different-contents": _process(
        KPN, "2026-10-14", KPN_RENAMED,
        status=f"OneDrive kept the other file and named this one kpn-factuur-123456 1.pdf.\n"
               f"Uploaded to Informer: yes (2026-10-07) · Uploaded to OneDrive: yes ({KPN_RENAMED})"),
    "onedrive-scanned-pdf-asks-date": [
        _calls(("read_pdf_text", {"path": "scan-factuur.pdf"})),
        _answer("scan-factuur.pdf has no text layer. What is its invoice date?"),
    ],
    "process-drive-failure": [
        _calls(("read_pdf_text", {"path": HOSTING})),
        _calls(("informer_check_purchase_invoice", {"path": HOSTING}),
               ("ms365_check_invoice_archive", {"path": HOSTING, "invoice_date": "2026-10-05"})),
        _calls(("informer_upload_purchase_invoice", {"path": HOSTING}),
               ("ms365_upload_to_onedrive", {"path": HOSTING, "invoice_date": "2026-10-05",
                                             "target_path": HOSTING_TARGET})),
        _answer("The Upload to Informer went through; OneDrive answered 503 Service Unavailable. "
                "Shall I do the Upload to OneDrive on its own later?\n"
                "Uploaded to Informer: yes (2026-10-07) · Uploaded to OneDrive: no"),
    ],
}


async def _run(scenario_id: str, script: list[AIMessage], scripted_model):
    return await run_scenario(BY_ID[scenario_id], model=scripted_model(script), model_name="scripted")


def test_the_archive_scenarios_are_in_the_dataset():
    assert ARCHIVE_IDS <= BY_ID.keys()
    assert {BY_ID[i].workflow for i in ARCHIVE_IDS} == {"invoice archive"}
    assert DATASET.dataset_version == "2026-11-24"


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario_id", sorted(ARCHIVE_IDS))
async def test_each_archive_scenario_passes_a_scripted_model_that_does_the_right_thing(scenario_id, scripted_model):
    run = await _run(scenario_id, RIGHT_SCRIPTS[scenario_id], scripted_model)

    assert (run.status, run.error) == ("completed", None)
    assert run.trajectory.passed, run.trajectory
    assert run.outcome.passed, run.outcome.detail
    assert run.passed


TOOL_FACTS = {  # scenario -> (tool, a line its output must hold): the seeded world backs the answer
    "processed-check-by-file": ("ms365_check_invoice_archive", f"Invoice archive as {OCTOBER}/kpn-factuur-123456.pdf"),
    "processed-list-by-month": ("ms365_list_invoice_archive", "CH-2026-1044.pdf"),
    "onedrive-name-clash-same-contents": ("ms365_check_invoice_archive",
                                          f"Invoice archive as {ADMIN}/2026/September/Factuur.pdf"),
    "onedrive-name-clash-different-contents": ("ms365_check_invoice_archive", KPN_RENAMED),
    "onedrive-only-informer-done": ("informer_check_purchase_invoice", "2026-10-06"),
    "onedrive-scanned-pdf-asks-date": ("read_pdf_text", "no text layer"),
    "process-approved": ("read_pdf_text", "05-10-2026"),
}


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario_id", sorted(TOOL_FACTS))
async def test_what_each_scenario_grades_comes_from_the_seeded_world(scenario_id, scripted_model):
    tool, fact = TOOL_FACTS[scenario_id]
    run = await _run(scenario_id, RIGHT_SCRIPTS[scenario_id], scripted_model)

    [output] = [c.output for c in run.tool_calls if c.name == tool]
    assert fact in output


@pytest.mark.asyncio
async def test_without_a_seeded_upload_log_informer_reports_no_earlier_upload(scripted_model):
    run = await _run("onedrive-only-asks-process", RIGHT_SCRIPTS["onedrive-only-asks-process"], scripted_model)

    [check] = [c for c in run.tool_calls if c.name == "informer_check_purchase_invoice"]
    assert check.status == "success"
    assert "already_uploaded_on" not in check.output


@pytest.mark.asyncio
async def test_a_process_filed_in_the_wrong_month_fails_the_outcome(scripted_model):
    wrong = f"{ADMIN}/2026/September/{HOSTING}"
    run = await _run("process-approved", _process(
        HOSTING, "2026-09-05", wrong,
        status=f"Uploaded to Informer: yes (2026-10-07) · Uploaded to OneDrive: yes ({wrong})"), scripted_model)

    assert run.outcome.archived_files == [wrong]
    assert not run.outcome.passed
    assert not run.passed


@pytest.mark.asyncio
async def test_a_process_that_writes_an_extra_file_fails_the_outcome(scripted_model):
    script = _process(HOSTING, "2026-10-05", HOSTING_TARGET,
                      status=f"Uploaded to Informer: yes (2026-10-07) · Uploaded to OneDrive: yes ({HOSTING_TARGET})")
    script[2] = _calls(
        ("informer_upload_purchase_invoice", {"path": HOSTING}),
        ("ms365_upload_to_onedrive", {"path": HOSTING, "invoice_date": "2026-10-05", "target_path": HOSTING_TARGET}),
        ("ms365_upload_to_onedrive", {"path": "scan-factuur.pdf", "invoice_date": "2026-10-01",
                                      "target_path": f"{OCTOBER}/scan-factuur.pdf"}))
    run = await _run("process-approved", script, scripted_model)

    assert sorted(run.outcome.archived_files) == [HOSTING_TARGET, f"{OCTOBER}/scan-factuur.pdf"]
    assert not run.outcome.passed


@pytest.mark.parametrize("half", ["informer_upload_purchase_invoice", "ms365_upload_to_onedrive"])
@pytest.mark.asyncio
async def test_a_process_that_uploads_only_one_half_fails_the_outcome(half, scripted_model):
    script = _process(HOSTING, "2026-10-05", HOSTING_TARGET,
                      status=f"Uploaded to Informer: yes (2026-10-07) · Uploaded to OneDrive: yes ({HOSTING_TARGET})")
    script[2] = AIMessage(content="", tool_calls=[c for c in script[2].tool_calls if c["name"] == half])
    run = await _run("process-approved", script, scripted_model)

    assert not run.outcome.passed


@pytest.mark.asyncio
async def test_the_name_clash_approval_shows_the_renamed_target_and_the_seeded_file_stays(scripted_model):
    run = await _run("onedrive-name-clash-different-contents", RIGHT_SCRIPTS["onedrive-name-clash-different-contents"],
                     scripted_model)

    [approval] = run.interrupts
    assert KPN_RENAMED in approval.actions
    assert run.outcome.archived_files == [KPN_RENAMED]  # the seeded kpn-factuur-123456.pdf is not counted


@pytest.mark.asyncio
async def test_the_drive_failure_fails_only_the_drive_and_the_informer_upload_is_sent(scripted_model):
    run = await _run("process-drive-failure", RIGHT_SCRIPTS["process-drive-failure"], scripted_model)

    status = {c.name: c.status for c in run.tool_calls}
    assert status["ms365_check_invoice_archive"] == "error"
    assert run.outcome.upload_count == 1
    upload = next(c for c in run.tool_calls if c.name == "ms365_upload_to_onedrive")
    assert "503" in upload.output
    assert run.outcome.archived_files == []


@pytest.mark.asyncio
async def test_without_a_drive_failure_the_switch_is_cleared(scripted_model, monkeypatch):
    monkeypatch.setenv("FIXTURE_WORLD_MS365_DRIVE_FAILURE", "transient")
    run = await _run("process-approved", RIGHT_SCRIPTS["process-approved"], scripted_model)

    assert run.outcome.passed, run.outcome.detail


@pytest.mark.asyncio
async def test_each_run_has_its_own_drive(scripted_model):
    first = await _run("process-approved", RIGHT_SCRIPTS["process-approved"], scripted_model)
    second = await _run("process-approved", RIGHT_SCRIPTS["process-approved"], scripted_model)

    assert first.outcome.passed and second.outcome.passed, second.outcome.detail
