"""
tests/test_save_outlook_attachment.py

Saving an Outlook attachment into the agent folder's outlook/ subfolder, at the tool seam: the
tools exactly as `load_all_tools(fixtures=True)` returns them, invoked directly, with the
agent folder in a temporary directory. The download goes through the stand-in MS365 server's
`download-bytes-to-file`; nothing reaches a real mailbox or the real ~/Downloads.
"""

import base64
import json

import pytest
import pytest_asyncio
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

import agent.tools.attachment_save as attachment_save
from agent.config import settings
from agent.graph import build_graph
from agent.model_binding import bind_agent_tools
from agent.tools import load_all_tools
from agent.tools.classification import is_read
from fixture_world.clock import SEED_TODAY
from fixture_world.ms365 import load_seed

MESSAGE_ID = "AAMkAGZpeHR1cmUAMESSAGE01"  # CloudHost's October invoice: a PDF and an inline logo
PDF_ID = "AAMkAGZpeHR1cmUAATTACH01"
LOGO_ID = "AAMkAGZpeHR1cmUAATTACH02"
PDF_NAME = "CH-2026-1044.pdf"
LOGO_NAME = "cloudhost-logo.png"


def _seeded_bytes(attachment_id: str) -> bytes:
    [attachment] = [a for a in load_seed("attachments")[MESSAGE_ID] if a["id"] == attachment_id]
    return base64.b64decode(attachment["contentBytes"])


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


async def _save(tools, attachment_id=PDF_ID, file_name=PDF_NAME, message_id=MESSAGE_ID, **extra) -> str:
    args = {"message_id": message_id, "attachment_id": attachment_id, "file_name": file_name, **extra}
    return await tools["ms365_save_attachment"].ainvoke(args)


@pytest.mark.asyncio
async def test_a_save_writes_the_seeded_bytes_into_outlook_and_names_the_path(tools, agent_folder):
    result = await _save(tools)

    saved = agent_folder / "outlook" / PDF_NAME
    assert saved.read_bytes() == _seeded_bytes(PDF_ID)
    assert str(saved) in result
    assert str(len(_seeded_bytes(PDF_ID))) in result
    assert not result.startswith("Error:")


@pytest.mark.asyncio
async def test_the_first_save_creates_the_agent_folder_and_its_outlook_subfolder(tools, agent_folder):
    assert not agent_folder.exists()

    await _save(tools)

    assert sorted(p.name for p in agent_folder.iterdir()) == ["outlook"]
    assert [p.name for p in (agent_folder / "outlook").iterdir()] == [PDF_NAME]


@pytest.mark.asyncio
async def test_an_identical_repeat_writes_nothing_and_returns_the_existing_path(tools, agent_folder):
    await _save(tools)

    result = await _save(tools)

    assert "already saved as" in result.lower()
    assert str(agent_folder / "outlook" / PDF_NAME) in result
    assert [p.name for p in (agent_folder / "outlook").iterdir()] == [PDF_NAME]


@pytest.mark.asyncio
async def test_different_contents_with_the_same_name_get_1_then_2_and_nothing_is_overwritten(
    tools, agent_folder
):
    outlook = agent_folder / "outlook"
    outlook.mkdir(parents=True)
    (outlook / PDF_NAME).write_bytes(b"September's invoice")
    (outlook / "CH-2026-1044 (1).pdf").write_bytes(b"August's invoice")

    result = await _save(tools)

    assert (outlook / PDF_NAME).read_bytes() == b"September's invoice"
    assert (outlook / "CH-2026-1044 (1).pdf").read_bytes() == b"August's invoice"
    assert (outlook / "CH-2026-1044 (2).pdf").read_bytes() == _seeded_bytes(PDF_ID)
    assert str(outlook / "CH-2026-1044 (2).pdf") in result
    assert len(list(outlook.iterdir())) == 3  # no temporary file left behind


@pytest.mark.asyncio
async def test_a_file_name_mismatch_is_refused_and_writes_nothing(tools, agent_folder):
    result = await _save(tools, file_name="harmless.txt")

    assert result.startswith("Error:")
    assert PDF_NAME in result
    assert not (agent_folder / "outlook").exists() or not any((agent_folder / "outlook").iterdir())


@pytest.mark.asyncio
async def test_an_unknown_attachment_or_message_is_refused_and_writes_nothing(tools, agent_folder):
    unknown_attachment = await _save(tools, attachment_id="AAMkAGZpeHR1cmUAATTACH99")
    unknown_message = await _save(tools, message_id="AAMkAGZpeHR1cmUAMESSAGE99")

    assert unknown_attachment.startswith("Error:")
    assert unknown_message.startswith("Error:")
    assert not (agent_folder / "outlook").exists() or not any((agent_folder / "outlook").iterdir())


def test_a_name_that_tries_to_escape_the_subfolder_still_lands_inside_it(agent_folder):
    # The real name comes from the email, so a hostile sender can choose it. A download lands
    # in outlook/ under a temporary name first; the shared rules choose the final name.
    temporary = attachment_save.temporary_path("outlook")
    temporary.write_bytes(b"hostile")

    result = attachment_save.place_file(temporary, "../x.pdf", "outlook")

    assert (agent_folder / "outlook" / "x.pdf").read_bytes() == b"hostile"
    assert not (agent_folder / "x.pdf").exists()
    assert str(agent_folder / "outlook" / "x.pdf") in result
    assert [p.name for p in (agent_folder / "outlook").iterdir()] == ["x.pdf"]


@pytest.mark.asyncio
async def test_the_size_cap_refuses_an_oversized_attachment_before_downloading(tools, agent_folder, monkeypatch):
    monkeypatch.setattr(attachment_save, "MAX_ATTACHMENT_BYTES", 100)

    result = await _save(tools)

    assert result.startswith("Error:")
    assert "too large" in result.lower()
    assert not (agent_folder / "outlook").exists() or not any((agent_folder / "outlook").iterdir())


@pytest.mark.asyncio
async def test_a_download_over_the_cap_is_refused_and_leaves_no_temporary_file(tools, agent_folder, monkeypatch):
    # The listed size is under the cap, the bytes written are not: refused after the download.
    monkeypatch.setattr(attachment_save, "check_listed_size", lambda file_name, size: None)
    monkeypatch.setattr(attachment_save, "MAX_ATTACHMENT_BYTES", 100)

    result = await _save(tools)

    assert result.startswith("Error:")
    assert "too large" in result.lower()
    assert list((agent_folder / "outlook").iterdir()) == []


@pytest.mark.asyncio
async def test_an_inline_attachment_is_refused_without_include_inline_and_saved_with_it(tools, agent_folder):
    refused = await _save(tools, attachment_id=LOGO_ID, file_name=LOGO_NAME)

    assert refused.startswith("Error:")
    assert not (agent_folder / "outlook").exists() or not any((agent_folder / "outlook").iterdir())

    saved = await _save(tools, attachment_id=LOGO_ID, file_name=LOGO_NAME, include_inline=True)

    assert (agent_folder / "outlook" / LOGO_NAME).read_bytes() == _seeded_bytes(LOGO_ID)
    assert not saved.startswith("Error:")


@pytest.mark.asyncio
async def test_each_mailbox_saves_only_into_its_own_subfolder(tools, agent_folder):
    await _save(tools)
    await tools["save_gmail_attachment"].ainvoke(
        {"message_id": "gmsg004", "attachment_id": "1", "file_name": "energy-bill-2026-10.pdf"}
    )

    assert [p.name for p in (agent_folder / "outlook").iterdir()] == [PDF_NAME]
    assert [p.name for p in (agent_folder / "gmail").iterdir()] == ["energy-bill-2026-10.pdf"]


@pytest.mark.asyncio
async def test_the_save_tool_is_bound_as_a_write_action_and_the_raw_download_is_not_bound(tools):
    assert "ms365_save_attachment" in tools
    assert not is_read(tools["ms365_save_attachment"])
    assert not any("download-bytes-to-file" in name for name in tools)
    # The lookup stays a plain read, not wrapped.
    assert is_read(tools["ms365_list-mail-attachments"])


@pytest.mark.asyncio
async def test_the_save_tools_schema_binds_cleanly_for_gemini(tools):
    model = ChatGoogleGenerativeAI(model="gemini-3.8-flash", google_api_key="test-key")
    bound = bind_agent_tools(model, [tools["ms365_save_attachment"]])

    [spec] = bound.kwargs["tools"]
    parameters = spec["function"]["parameters"]
    assert sorted(parameters["properties"]) == ["attachment_id", "file_name", "include_inline", "message_id"]
    assert sorted(parameters["required"]) == ["attachment_id", "file_name", "message_id"]
    assert parameters["properties"]["include_inline"]["default"] is False
    assert "additionalProperties" not in json.dumps(spec)


@pytest.mark.asyncio
async def test_the_save_pauses_for_approval_and_a_reject_writes_nothing(tools, agent_folder, scripted_model):
    call = {
        "id": "save",
        "name": "ms365_save_attachment",
        "args": {"message_id": MESSAGE_ID, "attachment_id": PDF_ID, "file_name": PDF_NAME},
    }
    model = scripted_model([AIMessage(content="", tool_calls=[call]), AIMessage(content="Not saved.")])
    graph = build_graph(checkpointer=InMemorySaver(), tools=list(tools.values()), model=model)
    config = {"configurable": {"thread_id": "save-outlook"}}

    result = await graph.ainvoke({"messages": [HumanMessage(content="Save the CloudHost invoice.")]}, config=config)

    assert "__interrupt__" in result
    assert "ms365_save_attachment" in result["__interrupt__"][0].value["actions"]
    assert not agent_folder.exists()

    result = await graph.ainvoke(Command(resume="reject"), config=config)

    [shown] = [m for m in result["messages"] if isinstance(m, ToolMessage) and m.tool_call_id == "save"]
    assert "rejected by the user" in shown.content
    assert not agent_folder.exists()
