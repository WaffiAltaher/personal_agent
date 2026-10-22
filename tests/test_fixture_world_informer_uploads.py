"""
tests/test_fixture_world_informer_uploads.py

The Fixture world's Informer server is a new process for every tool call, so its upload log
has to outlive the process: an upload in one call is seen by a check in the next.
Loaded over real MCP (stdio) exactly as `--fixtures` loads the tools.
"""

import json

import pytest

from agent.tools import load_all_tools
from fixture_world import informer as fixture_informer

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
    return downloads


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


def test_without_a_configured_path_the_log_is_one_stable_file(monkeypatch):
    monkeypatch.delenv(fixture_informer.UPLOAD_LOG_ENV, raising=False)

    assert fixture_informer.upload_log_path() == fixture_informer.upload_log_path()
    assert fixture_informer.upload_log_path().is_absolute()
