# tests/informer_server/test_purchase_upload.py
"""Purchase invoice check and upload tools (ADR-012): path safety, PDF validation, hand-over."""

from pathlib import Path

import pytest

from agent.tools.informer import READ_TOOLS
from fixture_world.purchase_handover import RecordingHandover

MINIMAL_PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
NOT_PDF = b"not a pdf file\n"


@pytest.fixture
def downloads(tmp_path) -> Path:
    folder = tmp_path / "Downloads"
    folder.mkdir()
    return folder


@pytest.fixture
def settings_with_downloads(informer_settings, downloads):
    return informer_settings.model_copy(update={"downloads_dir": downloads})


@pytest.fixture
def handover():
    return RecordingHandover()


def write_pdf(folder: Path, name: str, content: bytes = MINIMAL_PDF) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_bytes(content)
    return path


@pytest.mark.asyncio
async def test_without_handover_neither_upload_tool_is_listed(connect, settings_with_downloads, call_tool):
    async with connect(settings_with_downloads) as session:
        init = await session.initialize()
        listed = await session.list_tools()

    names = {t.name for t in listed.tools}
    assert "check_purchase_invoice" not in names
    assert "upload_purchase_invoice" not in names
    assert "upload" not in (init.instructions or "").lower()


@pytest.mark.asyncio
async def test_with_handover_instructions_mention_purchase_uploads(
    connect, settings_with_downloads, handover, call_tool,
):
    async with connect(settings_with_downloads, handover=handover) as session:
        init = await session.initialize()

    assert "purchase invoice upload" in (init.instructions or "").lower()


@pytest.mark.asyncio
async def test_check_reports_name_folder_and_size(
    connect, settings_with_downloads, handover, downloads, call_tool,
):
    write_pdf(downloads / "invoices", "scan-2026.pdf")

    async with connect(settings_with_downloads, handover=handover) as session:
        is_error, payload = await call_tool(
            session, "check_purchase_invoice", path=str(downloads / "invoices" / "scan-2026.pdf"),
        )

    assert not is_error
    assert payload == {
        "file_name": "scan-2026.pdf",
        "folder": str(downloads / "invoices"),
        "size": len(MINIMAL_PDF),
    }


@pytest.mark.parametrize("path_factory,reason_fragment", [
    ("outside_downloads", "downloads"),
    ("symlink_outside", "downloads"),
    ("dotdot_escape", "downloads"),
    ("wrong_extension", "pdf"),
    ("not_pdf_content", "pdf"),
    ("over_size_cap", "size"),
])
@pytest.mark.asyncio
async def test_check_refuses_invalid_paths(
    connect, settings_with_downloads, handover, downloads, call_tool, path_factory, reason_fragment, tmp_path,
):
    path = _invalid_path(path_factory, downloads, tmp_path)

    async with connect(settings_with_downloads, handover=handover) as session:
        is_error, text = await call_tool(session, "check_purchase_invoice", path=str(path))

    assert is_error
    assert reason_fragment.lower() in text.lower()


@pytest.mark.parametrize("path_factory", [
    "outside_downloads", "symlink_outside", "dotdot_escape", "wrong_extension", "not_pdf_content", "over_size_cap",
])
@pytest.mark.asyncio
async def test_upload_refuses_invalid_paths_and_hands_nothing_over(
    connect, settings_with_downloads, handover, downloads, call_tool, path_factory, tmp_path,
):
    path = _invalid_path(path_factory, downloads, tmp_path)

    async with connect(settings_with_downloads, handover=handover) as session:
        is_error, _text = await call_tool(session, "upload_purchase_invoice", path=str(path))

    assert is_error
    assert handover.uploads == []


@pytest.mark.asyncio
async def test_upload_hands_over_exactly_one_matching_file(
    connect, settings_with_downloads, handover, downloads, call_tool,
):
    pdf_path = write_pdf(downloads, "supplier-march.pdf")

    async with connect(settings_with_downloads, handover=handover) as session:
        is_error, payload = await call_tool(session, "upload_purchase_invoice", path=str(pdf_path))

    assert not is_error
    assert handover.uploads == [("supplier-march.pdf", MINIMAL_PDF)]
    assert payload.get("file_name") == "supplier-march.pdf"


@pytest.mark.asyncio
async def test_handover_failure_is_reported_and_attempted_once(
    connect, settings_with_downloads, downloads, call_tool,
):
    handover = RecordingHandover(fail_with="hand-over unavailable")
    pdf_path = write_pdf(downloads, "fail-me.pdf")

    async with connect(settings_with_downloads, handover=handover) as session:
        is_error, text = await call_tool(session, "upload_purchase_invoice", path=str(pdf_path))

    assert is_error
    assert "hand-over unavailable" in text
    assert handover.attempts == 1
    assert handover.uploads == []


def test_upload_is_not_on_read_allowlist_check_is():
    assert "check_purchase_invoice" in READ_TOOLS
    assert "upload_purchase_invoice" not in READ_TOOLS


def _invalid_path(kind: str, downloads: Path, tmp_path: Path) -> Path:
    if kind == "outside_downloads":
        outside = tmp_path / "secret.pdf"
        outside.write_bytes(MINIMAL_PDF)
        return outside
    if kind == "symlink_outside":
        outside = tmp_path / "real.pdf"
        outside.write_bytes(MINIMAL_PDF)
        link = downloads / "link.pdf"
        link.symlink_to(outside)
        return link
    if kind == "dotdot_escape":
        outside = tmp_path / "escape.pdf"
        outside.write_bytes(MINIMAL_PDF)
        return downloads / ".." / "escape.pdf"
    if kind == "wrong_extension":
        path = downloads / "invoice.txt"
        path.write_bytes(MINIMAL_PDF)
        return path
    if kind == "not_pdf_content":
        path = downloads / "fake.pdf"
        path.write_bytes(NOT_PDF)
        return path
    if kind == "over_size_cap":
        path = downloads / "huge.pdf"
        path.write_bytes(MINIMAL_PDF + b"0" * (2 * 1024 * 1024))
        return path
    raise ValueError(kind)
