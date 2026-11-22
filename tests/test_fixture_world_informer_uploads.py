"""
tests/test_fixture_world_informer_uploads.py

The Fixture world's Informer server is a new process for every tool call, so its upload log
has to outlive the process: an upload in one call is seen by a check in the next.
Loaded over real MCP (stdio) exactly as `--fixtures` loads the tools.
"""

import json
import os
import sys

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from agent.tools import load_all_tools, ms365_mcp
from fixture_world import informer as fixture_informer, ms365 as fixture_ms365

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


def _payload(result) -> dict:
    text = result if isinstance(result, str) else "".join(block["text"] for block in result)
    return json.loads(text)


@pytest.fixture
def fixture_world_downloads(monkeypatch, tmp_path):
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    monkeypatch.setenv(fixture_informer.DOWNLOADS_ENV, str(downloads))
    monkeypatch.setenv("FIXTURE_WORLD_TODAY", "2026-10-07")
    monkeypatch.setenv(fixture_informer.UPLOAD_LOG_ENV, str(tmp_path / "log" / "uploads.jsonl"))
    monkeypatch.setenv(fixture_ms365.SENT_ENV, str(tmp_path / "sent.jsonl"))
    return downloads


@pytest.mark.asyncio
async def test_an_upload_is_sent_by_the_ms365_stand_in_as_one_email(fixture_world_downloads, tmp_path):
    pdf = fixture_world_downloads / "march.pdf"
    pdf.write_bytes(PDF)
    tools, _ = await load_all_tools(fixtures=True)
    upload = next(t for t in tools if t.name == "informer_upload_purchase_invoice")

    await upload.ainvoke({"path": str(pdf)})

    [message] = fixture_ms365.sent_messages(tmp_path / "sent.jsonl")
    assert message["sender"] == fixture_informer.INVOICE_MAILBOX
    assert message["to"] == [fixture_informer.INCOMING_ADDRESS]
    assert (message["cc"], message["bcc"]) == ([], [])
    assert message["attachments"] == [{"name": "march.pdf", "content_type": "application/pdf", "content": PDF}]


@pytest.mark.asyncio
async def test_an_upload_is_seen_by_a_later_check_in_another_process(fixture_world_downloads):
    first = fixture_world_downloads / "march.pdf"
    first.write_bytes(PDF)
    copy = fixture_world_downloads / "copy-of-march.pdf"
    copy.write_bytes(PDF)
    tools, notices = await load_all_tools(fixtures=True)
    by_name = {t.name: t for t in tools}
    assert notices == []

    await by_name["informer_upload_purchase_invoice"].ainvoke({"path": str(first)})
    checked = _payload(await by_name["informer_check_purchase_invoice"].ainvoke({"path": str(copy)}))

    assert checked["already_uploaded_on"] == "2026-10-07"


@pytest.mark.asyncio
async def test_a_login_error_names_the_same_pinned_login_command_as_the_real_server(
    fixture_world_downloads, monkeypatch,
):
    monkeypatch.setenv(fixture_ms365.FAILURE_ENV, "logged-out")
    pdf = fixture_world_downloads / "march.pdf"
    pdf.write_bytes(PDF)
    tools, _ = await load_all_tools(fixtures=True)
    upload = next(t for t in tools if t.name == "informer_upload_purchase_invoice")

    result = await upload.ainvoke({"path": str(pdf)})

    assert ms365_mcp.LOGIN.command in str(result)


def test_the_ms365_stand_in_gets_only_the_fixture_world_variables_it_reads(monkeypatch, tmp_path):
    monkeypatch.setenv(fixture_ms365.SENT_ENV, str(tmp_path / "sent.jsonl"))
    monkeypatch.setenv(fixture_ms365.SEND_FAILURE_ENV, "transient")
    monkeypatch.setenv(fixture_informer.UPLOAD_LOG_ENV, str(tmp_path / "uploads.jsonl"))
    monkeypatch.setenv(fixture_informer.DOWNLOADS_ENV, str(tmp_path))
    monkeypatch.setenv("INFORMER_DOWNLOADS_DIR", str(tmp_path))

    params = fixture_informer.ms365_stand_in_parameters()

    assert params.args[:2] == ["-m", "fixture_world.ms365"]
    assert params.env[fixture_ms365.SENT_ENV] == str(tmp_path / "sent.jsonl")
    assert params.env[fixture_ms365.SEND_FAILURE_ENV] == "transient"
    for name in (fixture_informer.UPLOAD_LOG_ENV, fixture_informer.DOWNLOADS_ENV, "INFORMER_DOWNLOADS_DIR"):
        assert name not in params.env


def test_the_ms365_stand_in_gets_only_the_system_basics_from_the_shell(monkeypatch):
    # Run by hand from a shell, nothing else in it reaches the stand-in.
    monkeypatch.setenv("AGENT_DECOY_SECRET", "made-up-decoy")
    monkeypatch.setenv("ENABLED_TOOLS", ".*")

    env = fixture_informer.ms365_stand_in_parameters().env

    assert "AGENT_DECOY_SECRET" not in env
    assert "ENABLED_TOOLS" not in env
    assert env["PATH"] == os.environ["PATH"]


@pytest.mark.asyncio
async def test_run_without_the_agents_pin_a_login_error_names_no_none_package(fixture_world_downloads, monkeypatch):
    monkeypatch.setenv(fixture_ms365.FAILURE_ENV, "logged-out")
    monkeypatch.delenv("INFORMER_MS365_PACKAGE", raising=False)
    pdf = fixture_world_downloads / "march.pdf"
    pdf.write_bytes(PDF)
    env = {key: value for key, value in os.environ.items() if key != "INFORMER_MS365_PACKAGE"}
    params = StdioServerParameters(command=sys.executable, args=["-m", "fixture_world.informer"], env=env)

    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        result = await session.call_tool("upload_purchase_invoice", {"path": str(pdf)})

    text = "".join(block.text for block in result.content)
    assert "Not logged in to Microsoft 365" in text
    assert "npx -y None" not in text


def test_without_a_configured_path_the_log_is_one_stable_file(monkeypatch):
    monkeypatch.delenv(fixture_informer.UPLOAD_LOG_ENV, raising=False)

    assert fixture_informer.upload_log_path() == fixture_informer.upload_log_path()
    assert fixture_informer.upload_log_path().is_absolute()
