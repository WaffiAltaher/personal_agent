"""
tests/test_process_purchase_invoice.py

A Process (ADR-020): the model proposes the Upload to Informer and the Upload to OneDrive in one
turn, the graph asks for one Approval listing both, and both run. The seam is the graph with a
scripted model and the tools as `load_all_tools(fixtures=True)` binds them, so the Informer
upload is sent through the MS365 stand-in and the Upload to OneDrive lands in its drive.
"""

import pytest
import pytest_asyncio
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from agent.config import settings
from agent.graph import build_graph
from agent.tools import load_all_tools
from fixture_world import informer as fixture_informer
from fixture_world import ms365 as fixture_ms365
from fixture_world.pdfs import text_pdf

TARGET = "Documents/ittopia/admin/2026/November/hosting-2026-11.pdf"


@pytest.fixture
def world(tmp_path, monkeypatch):
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    monkeypatch.setattr(settings, "informer_downloads_dir", str(downloads))
    monkeypatch.setenv("INFORMER_DOWNLOADS_DIR", str(downloads))
    monkeypatch.setenv(fixture_informer.DOWNLOADS_ENV, str(downloads))
    monkeypatch.setenv(fixture_informer.UPLOAD_LOG_ENV, str(tmp_path / "informer-uploads.jsonl"))
    monkeypatch.setenv(fixture_ms365.SENT_ENV, str(tmp_path / "sent.jsonl"))
    monkeypatch.setenv(fixture_ms365.DRIVE_ENV, str(tmp_path / "drive"))
    return tmp_path, downloads


@pytest_asyncio.fixture
async def tools(world):
    tools, notices = await load_all_tools(fixtures=True)
    assert notices == []
    return tools


@pytest.mark.asyncio
async def test_a_process_is_one_approval_listing_both_uploads_and_both_run(world, tools, scripted_model):
    work, downloads = world
    pdf = downloads / "hosting-2026-11.pdf"
    pdf.write_bytes(text_pdf(["Factuur", "Factuurdatum: 03-11-2026"]))
    process = AIMessage(content="", tool_calls=[
        {"id": "informer", "name": "informer_upload_purchase_invoice", "args": {"path": str(pdf)}},
        {"id": "onedrive", "name": "ms365_upload_to_onedrive",
         "args": {"path": str(pdf), "invoice_date": "2026-11-03", "target_path": TARGET}},
    ])
    model = scripted_model([process, AIMessage(content="Processed hosting-2026-11.pdf.")])
    graph = build_graph(checkpointer=InMemorySaver(), tools=tools, model=model)
    config = {"configurable": {"thread_id": "process"}}

    result = await graph.ainvoke({"messages": [HumanMessage(content="Process the hosting invoice.")]}, config)

    [approval] = result["__interrupt__"]
    assert approval.value["tool_call_ids"] == ["informer", "onedrive"]
    assert "informer_upload_purchase_invoice" in approval.value["actions"]
    assert TARGET in approval.value["actions"]
    assert fixture_ms365.sent_messages(work / "sent.jsonl") == []

    result = await graph.ainvoke(Command(resume="approve"), config)

    assert "__interrupt__" not in result
    ran = {m.tool_call_id: m for m in result["messages"] if isinstance(m, ToolMessage)}
    assert ran["informer"].status != "error"
    assert ran["onedrive"].content.startswith(f"Uploaded to OneDrive: {TARGET}")
    [sent] = fixture_ms365.sent_messages(work / "sent.jsonl")
    assert [a["content"] for a in sent["attachments"]] == [pdf.read_bytes()]
    assert fixture_ms365.archived_files(work / "drive")[TARGET] == pdf.read_bytes()
