# tests/informer_server/test_purchase_upload.py
"""Purchase invoice check and upload tools (ADR-012): path safety, PDF validation, hand-over."""

from datetime import date
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
def settings_with_downloads(informer_settings, downloads, tmp_path):
    return informer_settings.model_copy(update={
        "downloads_dir": downloads,
        "purchase_upload_log": tmp_path / "state" / "purchase-uploads.jsonl",
        "today": date(2026, 10, 7),
    })


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


@pytest.mark.asyncio
async def test_bare_filename_resolves_inside_downloads_not_process_cwd(
    connect, settings_with_downloads, handover, downloads, call_tool, tmp_path, monkeypatch,
):
    write_pdf(downloads, "only-in-downloads.pdf", b"%PDF-1.4\ndownloads-bytes\n%%EOF\n")
    cwd_pdf = tmp_path / "only-in-downloads.pdf"
    cwd_pdf.write_bytes(b"%PDF-1.4\ncwd-bytes\n%%EOF\n")
    monkeypatch.chdir(tmp_path)

    async with connect(settings_with_downloads, handover=handover) as session:
        is_error, payload = await call_tool(
            session, "check_purchase_invoice", path="only-in-downloads.pdf",
        )

    assert not is_error
    assert payload["file_name"] == "only-in-downloads.pdf"
    assert payload["size"] == len(b"%PDF-1.4\ndownloads-bytes\n%%EOF\n")


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


# --- Upload log and allow_duplicate (ticket 17) -----------------------------------------


@pytest.mark.asyncio
async def test_check_reports_the_date_of_an_earlier_upload_under_any_name(
    connect, settings_with_downloads, handover, downloads, call_tool,
):
    first = write_pdf(downloads, "march.pdf")
    renamed = write_pdf(downloads / "copies", "scan-0042.pdf")  # same contents, other name and folder

    async with connect(settings_with_downloads, handover=handover) as session:
        await call_tool(session, "upload_purchase_invoice", path=str(first))
        is_error, payload = await call_tool(session, "check_purchase_invoice", path=str(renamed))

    assert not is_error
    assert payload["already_uploaded_on"] == "2026-10-07"
    assert "already uploaded on 2026-10-07" in payload["warning"]


@pytest.mark.asyncio
async def test_repeat_upload_is_refused_with_the_earlier_date_and_hands_nothing_over(
    connect, settings_with_downloads, handover, downloads, call_tool,
):
    first = write_pdf(downloads, "march.pdf")
    again = write_pdf(downloads, "march (1).pdf")

    async with connect(settings_with_downloads, handover=handover) as session:
        await call_tool(session, "upload_purchase_invoice", path=str(first))
        is_error, text = await call_tool(session, "upload_purchase_invoice", path=str(again))

    assert is_error
    assert "already uploaded on 2026-10-07" in text
    assert "allow_duplicate" in text
    assert handover.uploads == [("march.pdf", MINIMAL_PDF)]


@pytest.mark.asyncio
async def test_allow_duplicate_hands_the_repeat_over(
    connect, settings_with_downloads, handover, downloads, call_tool,
):
    first = write_pdf(downloads, "march.pdf")
    again = write_pdf(downloads, "march (1).pdf")

    async with connect(settings_with_downloads, handover=handover) as session:
        await call_tool(session, "upload_purchase_invoice", path=str(first))
        is_error, _ = await call_tool(
            session, "upload_purchase_invoice", path=str(again), allow_duplicate=True,
        )

    assert not is_error
    assert handover.uploads == [("march.pdf", MINIMAL_PDF), ("march (1).pdf", MINIMAL_PDF)]


@pytest.mark.asyncio
async def test_a_failed_upload_is_not_logged_as_uploaded(
    connect, settings_with_downloads, downloads, call_tool,
):
    failing = RecordingHandover(fail_with="hand-over unavailable")
    working = RecordingHandover()
    pdf_path = write_pdf(downloads, "retry-me.pdf")

    async with connect(settings_with_downloads, handover=failing) as session:
        failed, _ = await call_tool(session, "upload_purchase_invoice", path=str(pdf_path))
        _, checked = await call_tool(session, "check_purchase_invoice", path=str(pdf_path))
    async with connect(settings_with_downloads, handover=working) as session:
        retried, _ = await call_tool(session, "upload_purchase_invoice", path=str(pdf_path))

    assert failed
    assert "already_uploaded_on" not in checked
    assert not retried  # not refused as a duplicate
    assert working.uploads == [("retry-me.pdf", MINIMAL_PDF)]


@pytest.mark.asyncio
async def test_a_refused_upload_is_not_logged_as_uploaded(
    connect, settings_with_downloads, handover, downloads, call_tool,
):
    first = write_pdf(downloads, "march.pdf")
    again = write_pdf(downloads, "march (1).pdf")
    log = settings_with_downloads.purchase_upload_log

    async with connect(settings_with_downloads, handover=handover) as session:
        await call_tool(session, "upload_purchase_invoice", path=str(first))
        await call_tool(session, "upload_purchase_invoice", path=str(again))  # refused
        await call_tool(session, "upload_purchase_invoice", path=str(_invalid_path("not_pdf_content", downloads, downloads.parent)))

    assert len(log.read_text().splitlines()) == 1  # only the one real hand-over


@pytest.mark.asyncio
async def test_different_contents_are_neither_reported_nor_refused(
    connect, settings_with_downloads, handover, downloads, call_tool,
):
    first = write_pdf(downloads, "march.pdf")
    other = write_pdf(downloads, "april.pdf", MINIMAL_PDF + b"%different\n")

    async with connect(settings_with_downloads, handover=handover) as session:
        await call_tool(session, "upload_purchase_invoice", path=str(first))
        _, checked = await call_tool(session, "check_purchase_invoice", path=str(other))
        is_error, _ = await call_tool(session, "upload_purchase_invoice", path=str(other))

    assert "already_uploaded_on" not in checked and "warning" not in checked
    assert not is_error
    assert [name for name, _ in handover.uploads] == ["march.pdf", "april.pdf"]


@pytest.mark.asyncio
async def test_the_upload_log_outlives_the_server_process(
    connect, settings_with_downloads, downloads, call_tool,
):
    """The agent starts a new server per tool call, each with a new hand-over object."""
    pdf_path = write_pdf(downloads, "march.pdf")
    first, second = RecordingHandover(), RecordingHandover()

    async with connect(settings_with_downloads, handover=first) as session:
        await call_tool(session, "upload_purchase_invoice", path=str(pdf_path))
    async with connect(settings_with_downloads, handover=second) as session:
        is_error, text = await call_tool(session, "upload_purchase_invoice", path=str(pdf_path))

    assert is_error and "already uploaded on" in text
    assert second.uploads == []


@pytest.mark.asyncio
async def test_tool_descriptions_tell_the_model_to_ask_the_owner_before_reuploading(
    connect, settings_with_downloads, handover,
):
    async with connect(settings_with_downloads, handover=handover) as session:
        tools = {t.name: t for t in (await session.list_tools()).tools}

    for name in ("check_purchase_invoice", "upload_purchase_invoice"):
        assert "ask the owner" in " ".join(tools[name].description.lower().split())
    assert "allow_duplicate" in tools["upload_purchase_invoice"].description
    assert tools["upload_purchase_invoice"].inputSchema["properties"]["allow_duplicate"]["default"] is False


@pytest.mark.parametrize("tool", ["check_purchase_invoice", "upload_purchase_invoice"])
@pytest.mark.asyncio
async def test_over_cap_file_is_refused_without_being_read(
    connect, settings_with_downloads, handover, downloads, call_tool, monkeypatch, tool,
):
    cap = 100  # not the 2 MB default
    settings = settings_with_downloads.model_copy(update={"purchase_upload_max_bytes": cap})
    big = write_pdf(downloads, "big.pdf", MINIMAL_PDF + b"0" * (cap + 1 - len(MINIMAL_PDF)))

    def must_not_read(self):
        raise AssertionError("an over-cap file must be refused before it is read")

    monkeypatch.setattr(Path, "read_bytes", must_not_read)
    async with connect(settings, handover=handover) as session:
        is_error, text = await call_tool(session, tool, path=str(big))

    assert is_error
    assert "size cap" in text
    assert handover.uploads == []


@pytest.mark.asyncio
async def test_file_exactly_at_a_custom_cap_is_accepted(
    connect, settings_with_downloads, handover, downloads, call_tool,
):
    cap = 100
    settings = settings_with_downloads.model_copy(update={"purchase_upload_max_bytes": cap})
    at_cap = write_pdf(downloads, "at-cap.pdf", MINIMAL_PDF + b"0" * (cap - len(MINIMAL_PDF)))

    async with connect(settings, handover=handover) as session:
        is_error, payload = await call_tool(session, "check_purchase_invoice", path=str(at_cap))

    assert not is_error
    assert payload["size"] == cap


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
