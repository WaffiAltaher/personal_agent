"""
tests/test_save_gmail_attachment.py

Saving a Gmail attachment into the agent folder's gmail/ subfolder, at the tool seam: the
tools exactly as `load_all_tools(fixtures=True)` returns them, invoked directly, with the
agent folder in a temporary directory. Nothing reaches Gmail or the real ~/Downloads.
"""

import base64

import pytest
import pytest_asyncio
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

import agent.tools.attachment_save as attachment_save
from agent.config import settings
from agent.graph import build_graph
from agent.tools import load_all_tools
from fixture_world.clock import SEED_TODAY
from fixture_world import google as fixture_google
from fixture_world.google import load_seed

MESSAGE_ID = "gmsg004"  # the energy bill: a PDF, a CSV that carries a Content-ID, an inline logo
# The listed attachment ID is the MIME part ID: Gmail's own attachment IDs change per fetch.
PDF_ID = "1"
LOGO_ID = "2"
CSV_ID = "3"
PDF_NAME = "energy-bill-2026-10.pdf"
LOGO_NAME = "logo.png"
CSV_NAME = "meter-readings.csv"
EMAIL_ID = "4"  # an attached email (message/rfc822): not a file
EMAIL_NAME = "Your new contract.eml"


def _seeded_message() -> dict:
    [message] = [m for m in load_seed("messages") if m["id"] == MESSAGE_ID]
    return message


def _seeded_data(part_id: str) -> str:
    message = _seeded_message()
    [part] = [p for p in message["parts"] if p["partId"] == part_id]
    return message["attachmentData"][part["body"]["attachmentId"]]


def _seeded_bytes(part_id: str) -> bytes:
    data = _seeded_data(part_id)
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


@pytest.fixture
def agent_folder(tmp_path, monkeypatch):
    folder = tmp_path / "personal_agent"
    monkeypatch.setattr(settings, "agent_folder", str(folder))
    monkeypatch.setenv("FIXTURE_WORLD_TODAY", SEED_TODAY.isoformat())
    return folder


@pytest_asyncio.fixture
async def tools(agent_folder):
    tools, notices = await load_all_tools(fixtures=True)
    assert notices == []
    return {t.name: t for t in tools}


async def _save(tools, attachment_id=PDF_ID, file_name=PDF_NAME, **extra) -> str:
    args = {"message_id": MESSAGE_ID, "attachment_id": attachment_id, "file_name": file_name, **extra}
    return await tools["save_gmail_attachment"].ainvoke(args)


@pytest.mark.asyncio
async def test_a_save_writes_the_seeded_bytes_into_gmail_and_names_the_path(tools, agent_folder):
    result = await _save(tools)

    saved = agent_folder / "gmail" / PDF_NAME
    assert saved.read_bytes() == _seeded_bytes(PDF_ID)
    assert str(saved) in result
    assert str(len(_seeded_bytes(PDF_ID))) in result
    assert not result.startswith("Error:")


@pytest.mark.asyncio
async def test_the_first_save_creates_the_agent_folder_and_its_gmail_subfolder(tools, agent_folder):
    assert not agent_folder.exists()

    await _save(tools)

    assert sorted(p.name for p in agent_folder.iterdir()) == ["gmail"]
    assert [p.name for p in (agent_folder / "gmail").iterdir()] == [PDF_NAME]


@pytest.mark.asyncio
async def test_an_identical_repeat_writes_nothing_and_returns_the_existing_path(tools, agent_folder):
    await _save(tools)

    result = await _save(tools)

    assert "already saved as" in result.lower()
    assert str(agent_folder / "gmail" / PDF_NAME) in result
    assert [p.name for p in (agent_folder / "gmail").iterdir()] == [PDF_NAME]


@pytest.mark.asyncio
async def test_different_contents_with_the_same_name_get_1_then_2_and_nothing_is_overwritten(
    tools, agent_folder
):
    gmail = agent_folder / "gmail"
    gmail.mkdir(parents=True)
    (gmail / PDF_NAME).write_bytes(b"last month's bill")
    (gmail / "energy-bill-2026-10 (1).pdf").write_bytes(b"the month before")

    result = await _save(tools)

    assert (gmail / PDF_NAME).read_bytes() == b"last month's bill"
    assert (gmail / "energy-bill-2026-10 (1).pdf").read_bytes() == b"the month before"
    assert (gmail / "energy-bill-2026-10 (2).pdf").read_bytes() == _seeded_bytes(PDF_ID)
    assert str(gmail / "energy-bill-2026-10 (2).pdf") in result


@pytest.mark.asyncio
async def test_a_copy_already_saved_under_a_numbered_name_is_found(tools, agent_folder):
    gmail = agent_folder / "gmail"
    gmail.mkdir(parents=True)
    (gmail / PDF_NAME).write_bytes(b"last month's bill")
    (gmail / "energy-bill-2026-10 (1).pdf").write_bytes(_seeded_bytes(PDF_ID))

    result = await _save(tools)

    assert "already saved as" in result.lower()
    assert str(gmail / "energy-bill-2026-10 (1).pdf") in result
    assert {p.name for p in gmail.iterdir()} == {PDF_NAME, "energy-bill-2026-10 (1).pdf"}


@pytest.mark.asyncio
async def test_a_file_name_mismatch_is_refused_and_writes_nothing(tools, agent_folder):
    result = await _save(tools, file_name="harmless.txt")

    assert result.startswith("Error:")
    assert PDF_NAME in result
    assert not (agent_folder / "gmail").exists() or not any((agent_folder / "gmail").iterdir())


def test_a_name_that_tries_to_escape_the_subfolder_still_lands_inside_it(agent_folder):
    # The real name comes from the email, so a hostile sender can choose it.
    gmail = agent_folder / "gmail"

    assert attachment_save.bare_name("../x.pdf") == "x.pdf"
    assert attachment_save.bare_name("..\\..\\evil\\x.pdf") == "x.pdf"
    assert attachment_save.bare_name("/etc/passwd") == "passwd"
    assert attachment_save.bare_name("..") == "attachment"
    assert attachment_save.bare_name("") == "attachment"

    result = attachment_save.save_bytes(b"hostile", "../x.pdf", "gmail")

    assert (gmail / "x.pdf").read_bytes() == b"hostile"
    assert not (agent_folder / "x.pdf").exists()
    assert str(gmail / "x.pdf") in result


@pytest.mark.asyncio
async def test_the_size_cap_refuses_an_oversized_attachment(tools, agent_folder, monkeypatch):
    monkeypatch.setattr(attachment_save, "MAX_ATTACHMENT_BYTES", 100)

    result = await _save(tools)

    assert result.startswith("Error:")
    assert "too large" in result.lower()
    assert not (agent_folder / "gmail" / PDF_NAME).exists()


def test_the_size_cap_also_applies_to_the_actual_bytes(agent_folder, monkeypatch):
    monkeypatch.setattr(attachment_save, "MAX_ATTACHMENT_BYTES", 4)

    result = attachment_save.save_bytes(b"12345", "big.bin", "gmail")

    assert result.startswith("Error:")
    assert not (agent_folder / "gmail" / "big.bin").exists()


def test_the_cap_is_25_mb():
    assert attachment_save.MAX_ATTACHMENT_BYTES == 25 * 1024 * 1024


@pytest.mark.asyncio
async def test_an_inline_attachment_is_refused_without_include_inline_and_saved_with_it(tools, agent_folder):
    refused = await _save(tools, attachment_id=LOGO_ID, file_name=LOGO_NAME)

    assert refused.startswith("Error:")
    assert not (agent_folder / "gmail" / LOGO_NAME).exists()

    saved = await _save(tools, attachment_id=LOGO_ID, file_name=LOGO_NAME, include_inline=True)

    assert (agent_folder / "gmail" / LOGO_NAME).read_bytes() == _seeded_bytes(LOGO_ID)
    assert not saved.startswith("Error:")


@pytest.mark.asyncio
async def test_an_attached_email_is_refused_with_a_reason_and_writes_nothing(tools, agent_folder):
    result = await _save(tools, attachment_id=EMAIL_ID, file_name=EMAIL_NAME)

    assert result.startswith("Error:")
    assert EMAIL_NAME in result
    assert "only file attachments can be saved" in result
    assert not (agent_folder / "gmail").exists() or not any((agent_folder / "gmail").iterdir())


@pytest.mark.asyncio
async def test_reading_the_message_lists_the_pdf_and_hides_the_logo_by_default(tools):
    text = await tools["get_gmail_message"].ainvoke({"message_id": MESSAGE_ID})

    assert PDF_NAME in text
    assert f"attachment ID: {PDF_ID}" in text
    assert str(len(_seeded_bytes(PDF_ID))) in text
    assert LOGO_NAME not in text
    assert f"attachment ID: {LOGO_ID}" not in text

    with_inline = await tools["get_gmail_message"].ainvoke({"message_id": MESSAGE_ID, "include_inline": True})

    assert LOGO_NAME in with_inline
    assert f"attachment ID: {LOGO_ID}" in with_inline


@pytest.mark.asyncio
async def test_the_listed_attachment_id_stays_put_while_gmails_own_ids_change_per_fetch(tools, agent_folder):
    first = fixture_google.message_payload(MESSAGE_ID)["parts"][0]["body"]["attachmentId"]
    second = fixture_google.message_payload(MESSAGE_ID)["parts"][0]["body"]["attachmentId"]
    assert first != second  # the stand-in behaves like Gmail

    listed = await tools["get_gmail_message"].ainvoke({"message_id": MESSAGE_ID})
    assert listed == await tools["get_gmail_message"].ainvoke({"message_id": MESSAGE_ID})

    result = await _save(tools)

    assert (agent_folder / "gmail" / PDF_NAME).read_bytes() == _seeded_bytes(PDF_ID)
    assert not result.startswith("Error:")


@pytest.mark.asyncio
async def test_a_gmail_attachment_id_is_not_accepted_in_place_of_the_listed_one(tools, agent_folder):
    gmail_id = fixture_google.message_payload(MESSAGE_ID)["parts"][0]["body"]["attachmentId"]

    result = await _save(tools, attachment_id=gmail_id)

    assert result.startswith("Error:")
    assert not (agent_folder / "gmail" / PDF_NAME).exists()


@pytest.mark.asyncio
async def test_an_attachment_with_a_content_id_is_still_a_file_attachment(tools, agent_folder):
    # Gmail's own client gives ordinary attachments a Content-ID; Content-Disposition decides.
    text = await tools["get_gmail_message"].ainvoke({"message_id": MESSAGE_ID})
    assert f"{CSV_NAME} (" in text
    assert "inline" not in text.split(CSV_NAME, 1)[1].splitlines()[0]

    result = await _save(tools, attachment_id=CSV_ID, file_name=CSV_NAME)

    assert (agent_folder / "gmail" / CSV_NAME).read_bytes() == _seeded_bytes(CSV_ID)
    assert not result.startswith("Error:")


@pytest.mark.asyncio
async def test_has_attachment_finds_the_seeded_message_only(tools):
    text = await tools["search_gmail"].ainvoke({"query": "has:attachment"})

    assert f"ID:      {MESSAGE_ID}" in text
    assert "gmsg001" not in text


def test_seeded_attachment_data_is_base64url_not_standard_base64():
    data = _seeded_data(PDF_ID)

    assert "-" in data or "_" in data
    assert "+" not in data and "/" not in data


@pytest.mark.asyncio
async def test_the_save_pauses_for_approval_and_a_reject_writes_nothing(tools, agent_folder, scripted_model):
    call = {
        "id": "save",
        "name": "save_gmail_attachment",
        "args": {"message_id": MESSAGE_ID, "attachment_id": PDF_ID, "file_name": PDF_NAME},
    }
    model = scripted_model([AIMessage(content="", tool_calls=[call]), AIMessage(content="Not saved.")])
    graph = build_graph(checkpointer=InMemorySaver(), tools=list(tools.values()), model=model)
    config = {"configurable": {"thread_id": "save-gmail"}}

    result = await graph.ainvoke({"messages": [HumanMessage(content="Save the energy bill PDF.")]}, config=config)

    assert "__interrupt__" in result
    assert "save_gmail_attachment" in result["__interrupt__"][0].value["actions"]
    assert not agent_folder.exists()

    result = await graph.ainvoke(Command(resume="reject"), config=config)

    [shown] = [m for m in result["messages"] if isinstance(m, ToolMessage) and m.tool_call_id == "save"]
    assert "rejected by the user" in shown.content
    assert not agent_folder.exists()
