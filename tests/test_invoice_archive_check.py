"""
tests/test_invoice_archive_check.py

The Processed check, `ms365_check_invoice_archive(path, invoice_date)` (ADR-020). The seam is the
tool exactly as `load_all_tools(fixtures=True)` binds it, invoked directly: a local PDF in a
temporary Downloads folder, the MS365 stand-in's seeded drive in another. Nothing reaches a real
OneDrive.
"""

from importlib.resources import files

import pytest
import pytest_asyncio

from agent.config import Settings, settings
from agent.tools import load_all_tools
from agent.tools.classification import is_read
from fixture_world.ms365 import DRIVE_ENV, Failure, FailureSwitch
from fixture_world.pdfs import text_pdf

OCTOBER = "Documents/ittopia/admin/2026/October"
SEEDED_KPN = (files("fixture_world") / "data" / "ms365" / "drive" / OCTOBER / "kpn-factuur-123456.pdf").read_bytes()


@pytest.fixture
def drive(tmp_path, monkeypatch):
    path = tmp_path / "drive"
    monkeypatch.setenv(DRIVE_ENV, str(path))
    return path


@pytest.fixture
def downloads(tmp_path, monkeypatch):
    """The Downloads folder the Informer server checks, as the agent's settings name it."""
    folder = tmp_path / "Downloads"
    folder.mkdir()
    monkeypatch.setattr(settings, "informer_downloads_dir", str(folder))
    return folder


@pytest.fixture
def switch(tmp_path, monkeypatch):
    """Request it before `tools`: the stand-in's servers get the environment as it is when they load."""
    failure = FailureSwitch(tmp_path / "failure")
    for key, value in failure.env.items():
        monkeypatch.setenv(key, value)
    return failure


@pytest_asyncio.fixture
async def tools(drive, downloads):
    tools, notices = await load_all_tools(fixtures=True)
    assert notices == []
    return {t.name: t for t in tools}


async def _check(tools, path, invoice_date: str) -> str:
    return await tools["ms365_check_invoice_archive"].ainvoke({"path": str(path), "invoice_date": invoice_date})


def _new_invoice(downloads, name: str, *lines: str) -> object:
    path = downloads / name
    path.write_bytes(text_pdf(["Factuur", *lines]))
    return path


@pytest.mark.asyncio
async def test_the_check_is_bound_as_a_read(tools):
    assert is_read(tools["ms365_check_invoice_archive"])
    assert "contents" in tools["ms365_check_invoice_archive"].description


@pytest.mark.asyncio
async def test_same_contents_under_another_name_is_processed_naming_the_archived_file(tools, downloads):
    path = downloads / "invoice-from-kpn.pdf"
    path.write_bytes(SEEDED_KPN)

    result = await _check(tools, path, "2026-10-14")

    assert result.startswith("Processed")
    assert f"{OCTOBER}/kpn-factuur-123456.pdf" in result


@pytest.mark.asyncio
async def test_a_different_file_under_a_taken_name_is_not_processed_and_gets_onedrives_rename(tools, downloads):
    path = _new_invoice(downloads, "kpn-factuur-123456.pdf", "another month's bill")

    result = await _check(tools, path, "2026-10-01")

    assert result.startswith("Not Processed")
    assert f"Target path: {OCTOBER}/kpn-factuur-123456 1.pdf" in result
    assert "OneDrive will rename" in result


@pytest.mark.asyncio
async def test_the_rename_skips_names_already_taken_ignoring_case(tools, downloads, drive):
    await _check(tools, _new_invoice(downloads, "seed.pdf"), "2026-10-01")  # seeds the drive
    (drive / OCTOBER / "Factuur.pdf").write_bytes(text_pdf(["one"]))
    (drive / OCTOBER / "factuur 1.PDF").write_bytes(text_pdf(["two"]))
    path = _new_invoice(downloads, "FACTUUR.pdf", "three")

    result = await _check(tools, path, "2026-10-20")

    assert f"Target path: {OCTOBER}/FACTUUR 2.pdf" in result


@pytest.mark.asyncio
async def test_a_new_file_in_an_existing_month_gets_the_plain_target_path(tools, downloads):
    path = _new_invoice(downloads, "vodafone 2026-10 #7.pdf")

    result = await _check(tools, path, "2026-10-03")

    assert result.startswith("Not Processed")
    assert f"Target path: {OCTOBER}/vodafone 2026-10 #7.pdf" in result
    assert "rename" not in result


@pytest.mark.asyncio
@pytest.mark.parametrize(("invoice_date", "target"), [
    ("2026-11-02", "Documents/ittopia/admin/2026/November/new.pdf"),  # no month folder yet
    ("2027-01-05", "Documents/ittopia/admin/2027/January/new.pdf"),  # no year folder yet
])
async def test_a_missing_year_or_month_folder_is_not_processed_with_the_plain_target(tools, downloads,
                                                                                     invoice_date, target):
    result = await _check(tools, _new_invoice(downloads, "new.pdf"), invoice_date)

    assert result.startswith("Not Processed")
    assert f"Target path: {target}" in result


@pytest.mark.asyncio
async def test_contents_are_looked_up_only_in_the_invoice_dates_month(tools, downloads):
    path = downloads / "kpn-factuur-123456.pdf"
    path.write_bytes(SEEDED_KPN)

    result = await _check(tools, path, "2026-09-14")  # it is archived in October

    assert result.startswith("Not Processed")
    assert "Target path: Documents/ittopia/admin/2026/September/kpn-factuur-123456.pdf" in result


@pytest.mark.asyncio
async def test_a_relative_path_is_read_from_downloads(tools, downloads):
    (downloads / "personal_agent").mkdir()
    (downloads / "personal_agent" / "kpn.pdf").write_bytes(SEEDED_KPN)

    result = await _check(tools, "personal_agent/kpn.pdf", "2026-10-14")

    assert result.startswith("Processed")


@pytest.mark.asyncio
async def test_refused_files_never_reach_the_server(switch, tools, downloads, tmp_path):
    switch.set(Failure.TOOL_ERROR, times=1)  # the first server call fails: none of the refusals may use it up
    outside = tmp_path / "elsewhere.pdf"
    outside.write_bytes(SEEDED_KPN)
    text = downloads / "notes.txt"
    text.write_text("%PDF- not really")
    fake = downloads / "fake.pdf"
    fake.write_bytes(b"not a pdf at all")
    big = downloads / "big.pdf"
    with open(big, "wb") as f:
        f.write(b"%PDF-1.4\n")
        f.truncate(25 * 1024 * 1024 + 1)
    valid = _new_invoice(downloads, "valid.pdf")

    refusals = {
        "outside": await _check(tools, outside, "2026-10-14"),
        "not .pdf": await _check(tools, text, "2026-10-14"),
        "no magic": await _check(tools, fake, "2026-10-14"),
        "over 25 MB": await _check(tools, big, "2026-10-14"),
        "missing": await _check(tools, downloads / "nope.pdf", "2026-10-14"),
        "bad date": await _check(tools, valid, "14-10-2026"),
    }

    for reason, result in refusals.items():
        assert result.startswith("Error:"), (reason, result)
    assert "Downloads" in refusals["outside"]
    assert "25 MB" in refusals["over 25 MB"]
    assert "YYYY-MM-DD" in refusals["bad date"]
    # The switched failure is still waiting: no refusal called the server.
    assert "403" in await _check(tools, valid, "2026-10-14")


def test_the_downloads_folder_is_read_from_the_environment_or_env_file(monkeypatch):
    monkeypatch.setenv("INFORMER_DOWNLOADS_DIR", "/somewhere/Downloads")

    configured = Settings(_env_file=None, google_api_key="x", tavily_api_key="x",
                          langfuse_public_key="x", langfuse_secret_key="x")

    assert configured.informer_downloads_dir == "/somewhere/Downloads"
