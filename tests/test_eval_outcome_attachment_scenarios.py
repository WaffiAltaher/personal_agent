"""
Attachment eval scenarios: outcome grading from the agent folder and the Fixture world's upload log.

Seam: eval harness on the Fixture world with a scripted model (no live LLM).
"""

import base64
import json
import re

import pytest
from langchain_core.messages import AIMessage
from langchain_core.utils.function_calling import convert_to_openai_tool

import agent.graph as graph_module
from agent.config import settings
from agent.evals.harness import run_eval
from agent.evals.outcome import score_outcome
from agent.evals.scenarios import DEFAULT_DATASET, Dataset, Scenario, load_dataset
from conftest import ScriptedChatModel

DATASET = load_dataset(DEFAULT_DATASET)

GMAIL_SCENARIO = "attachment-gmail-save-approved"
OUTLOOK_SCENARIO = "attachment-outlook-save-rejected"
CHAIN_SCENARIO = "attachment-outlook-to-informer-approved"

GMAIL_MESSAGE = "gmsg004"
GMAIL_PDF = "energy-bill-2026-10.pdf"
OUTLOOK_MESSAGE = "AAMkAGZpeHR1cmUAMESSAGE01"
OUTLOOK_PDF_ID = "AAMkAGZpeHR1cmUAATTACH01"
OUTLOOK_PDF = "CH-2026-1044.pdf"

# The seeded bytes, read from the seed files as an independent source of truth.
_SEED = DEFAULT_DATASET.parents[2].parent / "fixture_world" / "data"
GMAIL_PDF_BYTES = base64.urlsafe_b64decode(
    next(m for m in json.loads((_SEED / "google" / "messages.json").read_text()) if m["id"] == "gmsg004")
    ["attachmentData"]["ANGjdJ8fixturePdf004"] + "=="
)
OUTLOOK_PDF_BYTES = base64.b64decode(
    json.loads((_SEED / "ms365" / "attachments.json").read_text())[OUTLOOK_MESSAGE][0]["contentBytes"]
)


def _scenario(scenario_id: str) -> Scenario:
    return next(s for s in DATASET.scenarios if s.id == scenario_id)


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


async def _run(scenario_id: str, script: list, scripted_model):
    results = await run_eval(
        Dataset(format_version=1, dataset_version="test", scenarios=[_scenario(scenario_id)]),
        model_name="scripted",
        model_factory=lambda s: scripted_model(script),
    )
    [run] = results.runs
    return run


def _gmail_save(attachment_id: str, file_name: str, call_id: str, **extra) -> AIMessage:
    return _call(
        "save_gmail_attachment",
        {"message_id": GMAIL_MESSAGE, "attachment_id": attachment_id, "file_name": file_name, **extra},
        call_id,
    )


def _outlook_save(attachment_id: str, file_name: str, call_id: str, **extra) -> AIMessage:
    return _call(
        "ms365_save_attachment",
        {"message_id": OUTLOOK_MESSAGE, "attachment_id": attachment_id, "file_name": file_name, **extra},
        call_id,
    )


@pytest.mark.asyncio
async def test_approved_gmail_save_passes_with_the_seeded_pdf_in_gmail(scripted_model):
    script = [
        _call("get_gmail_message", {"message_id": GMAIL_MESSAGE}, "read"),
        _gmail_save("1", GMAIL_PDF, "save"),
        _answer(f"Saved {GMAIL_PDF}."),
    ]
    real_folder = settings.agent_folder
    run = await _run(GMAIL_SCENARIO, script, scripted_model)
    assert run.outcome.passed, run.outcome.detail
    assert run.passed
    assert run.outcome.saved_files == [f"gmail/{GMAIL_PDF}"]
    assert re.search(r"/eval-[^/]+/Downloads/personal_agent/gmail/", run.tool_calls[1].output)
    assert settings.agent_folder == real_folder  # the run's temporary agent folder is not left behind


@pytest.mark.asyncio
async def test_gmail_save_that_also_saves_the_inline_logo_fails_on_outcome(scripted_model):
    script = [
        _call("get_gmail_message", {"message_id": GMAIL_MESSAGE, "include_inline": True}, "read"),
        _gmail_save("1", GMAIL_PDF, "save"),
        _gmail_save("2", "logo.png", "logo", include_inline=True),
        _answer("Saved the bill and the logo."),
    ]
    run = await _run(GMAIL_SCENARIO, script, scripted_model)
    assert run.trajectory.passed
    assert "gmail/logo.png" in run.outcome.saved_files
    assert not run.outcome.passed
    assert not run.passed


def test_gmail_save_scenario_fails_when_the_file_is_elsewhere_or_its_bytes_differ():
    scenario = _scenario(GMAIL_SCENARIO)
    good = score_outcome(scenario, [], final_answer="", saved={f"gmail/{GMAIL_PDF}": GMAIL_PDF_BYTES}, approvals=1)
    assert good.passed, good.detail
    for saved in ({f"gmail/{GMAIL_PDF}": b"%PDF-1.4\n"}, {f"outlook/{GMAIL_PDF}": GMAIL_PDF_BYTES}):
        assert not score_outcome(scenario, [], final_answer="", saved=saved, approvals=1).passed


@pytest.mark.asyncio
async def test_rejected_outlook_save_passes_with_nothing_in_the_agent_folder(scripted_model):
    script = [
        _call("ms365_list-mail-attachments", {"messageId": OUTLOOK_MESSAGE}, "list"),
        _outlook_save(OUTLOOK_PDF_ID, OUTLOOK_PDF, "save"),
        _answer("I did not save the invoice."),
    ]
    run = await _run(OUTLOOK_SCENARIO, script, scripted_model)
    assert [i.decision for i in run.interrupts] == ["reject"]
    assert run.outcome.saved_files == []
    assert run.outcome.passed, run.outcome.detail
    assert run.passed


def test_rejected_outlook_save_scenario_fails_when_anything_was_written():
    scenario = _scenario(OUTLOOK_SCENARIO)
    assert score_outcome(scenario, [], final_answer="", saved={}, approvals=1).passed
    for saved in ({f"outlook/{OUTLOOK_PDF}": OUTLOOK_PDF_BYTES}, {"outlook/.saving-1.part": b""}):
        assert not score_outcome(scenario, [], final_answer="", saved=saved, approvals=1).passed


def _saved_path(messages) -> str:
    """The full path the save returned to the model: "Saved <path> (<n> bytes)."."""
    [result] = [m for m in messages if getattr(m, "tool_call_id", None) == "save"]
    match = re.match(r"Saved (.+) \(\d+ bytes\)\.", str(result.content))
    assert match, result.content
    return match.group(1)


def _upload(path_from_messages) -> object:
    def reply(messages):
        path = path_from_messages(messages)
        return AIMessage(content="", tool_calls=[
            {"id": "check", "name": "informer_check_purchase_invoice", "args": {"path": path}},
            {"id": "upload", "name": "informer_upload_purchase_invoice", "args": {"path": path}},
        ])
    return reply


@pytest.mark.asyncio
async def test_outlook_to_informer_chain_passes_with_the_saved_file_uploaded(scripted_model):
    script = [
        _call("ms365_list-mail-attachments", {"messageId": OUTLOOK_MESSAGE}, "list"),
        _outlook_save(OUTLOOK_PDF_ID, OUTLOOK_PDF, "save"),
        _upload(_saved_path),
        _answer(f"Saved and uploaded {OUTLOOK_PDF}."),
    ]
    run = await _run(CHAIN_SCENARIO, script, scripted_model)
    assert run.outcome.saved_files == [f"outlook/{OUTLOOK_PDF}"]
    assert run.outcome.uploads == [OUTLOOK_PDF]
    assert len(run.interrupts) == 2
    assert run.outcome.passed, run.outcome.detail
    assert run.passed


@pytest.mark.asyncio
async def test_outlook_to_informer_chain_fails_when_a_different_file_is_uploaded(scripted_model):
    def seeded_download(messages):
        return _saved_path(messages).replace(f"personal_agent/outlook/{OUTLOOK_PDF}", "supplier-march.pdf")

    script = [
        _call("ms365_list-mail-attachments", {"messageId": OUTLOOK_MESSAGE}, "list"),
        _outlook_save(OUTLOOK_PDF_ID, OUTLOOK_PDF, "save"),
        _upload(seeded_download),
        _answer(f"Saved and uploaded {OUTLOOK_PDF}."),
    ]
    run = await _run(CHAIN_SCENARIO, script, scripted_model)
    assert run.trajectory.passed
    assert not run.outcome.passed


def test_outlook_to_informer_chain_fails_on_wrong_upload_bytes_or_one_approval():
    scenario = _scenario(CHAIN_SCENARIO)
    saved = {f"outlook/{OUTLOOK_PDF}": OUTLOOK_PDF_BYTES}
    expected = {OUTLOOK_PDF: OUTLOOK_PDF_BYTES}
    good = score_outcome(scenario, [(OUTLOOK_PDF, OUTLOOK_PDF_BYTES)], final_answer="",
                         expected_bytes=expected, saved=saved, approvals=2)
    assert good.passed, good.detail
    assert not score_outcome(scenario, [(OUTLOOK_PDF, b"%PDF-1.4\n")], final_answer="",
                             expected_bytes=expected, saved=saved, approvals=2).passed
    assert not score_outcome(scenario, [(OUTLOOK_PDF, OUTLOOK_PDF_BYTES)], final_answer="",
                             expected_bytes=expected, saved=saved, approvals=1).passed


GMAIL_STAND_INS = {"search_gmail", "get_gmail_message", "save_gmail_attachment"}


async def _offered_tools(scenario_id: str) -> set[str]:
    """The tool names the eval run offers the model in this scenario."""
    offered: set[str] = set()

    class RecordingModel(ScriptedChatModel):
        def bind_tools(self, tools, **kwargs):
            offered.update(convert_to_openai_tool(t)["function"]["name"] for t in tools)
            return self

    await run_eval(
        Dataset(format_version=1, dataset_version="test", scenarios=[_scenario(scenario_id)]),
        model_name="scripted",
        model_factory=lambda s: RecordingModel(messages=iter([_answer("Done.")])),
    )
    return offered


@pytest.mark.asyncio
async def test_the_gmail_stand_ins_are_offered_in_the_gmail_attachment_scenario():
    assert GMAIL_STAND_INS <= await _offered_tools(GMAIL_SCENARIO)


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario_id", [OUTLOOK_SCENARIO, CHAIN_SCENARIO, "inbox-logged-out"])
async def test_the_gmail_stand_ins_are_not_offered_in_scenarios_that_dont_need_them(scenario_id):
    assert not GMAIL_STAND_INS & await _offered_tools(scenario_id)
