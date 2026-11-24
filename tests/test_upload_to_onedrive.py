"""
tests/test_upload_to_onedrive.py

The Upload to OneDrive, `ms365_upload_to_onedrive(path, invoice_date, target_path)` (ADR-020). The seam
is the tool exactly as `load_all_tools(fixtures=True)` binds it, invoked directly: a local PDF in a
temporary Downloads folder, the MS365 stand-in's seeded drive in another, the stand-in's PUT
completing its upload session. Nothing reaches a real OneDrive.
"""

import asyncio
import json
import logging
from dataclasses import replace
from importlib.resources import files

import httpx
import pytest
import pytest_asyncio
from langchain_core.callbacks import BaseCallbackHandler

from agent.config import settings
from agent.tools import load_all_tools
from agent.tools.mcp_loader import load_mcp_server
from agent.tools.ms365_invoice_archive import UploadFailed, httpx_put, upload_to_onedrive
from agent.tools.ms365_mcp import ms365_fixture_server
from fixture_world.ms365 import (
    DRIVE_ENV,
    DRIVE_FAILURE_ENV,
    DRIVE_ID,
    UPLOAD_URL_SCHEME,
    Failure,
    FailureSwitch,
    archived_files,
    create_server,
)
from fixture_world.pdfs import text_pdf

ARCHIVE = "Documents/ittopia/admin"
OCTOBER = f"{ARCHIVE}/2026/October"
SEEDED = files("fixture_world") / "data" / "ms365" / "drive"
SEEDED_KPN = (SEEDED / OCTOBER / "kpn-factuur-123456.pdf").read_bytes()


@pytest.fixture
def drive(tmp_path, monkeypatch):
    path = tmp_path / "drive"
    monkeypatch.setenv(DRIVE_ENV, str(path))
    return path


@pytest.fixture
def downloads(tmp_path, monkeypatch):
    folder = tmp_path / "Downloads"
    folder.mkdir()
    monkeypatch.setattr(settings, "informer_downloads_dir", str(folder))
    return folder


@pytest_asyncio.fixture
async def tools(drive, downloads):
    tools, notices = await load_all_tools(fixtures=True)
    assert notices == []
    return {t.name: t for t in tools}


def _new_invoice(downloads, name: str, *lines: str):
    path = downloads / name
    path.write_bytes(text_pdf(["Factuur", *lines]))
    return path


async def _upload(tools, path, invoice_date: str, target_path: str, config=None) -> str:
    return await tools["ms365_upload_to_onedrive"].ainvoke(
        {"path": str(path), "invoice_date": invoice_date, "target_path": target_path}, config)


def _added(drive) -> dict[str, bytes]:
    """The archive's files that were not seeded."""
    seeded = {p.relative_to(SEEDED).as_posix() for p in _walk(SEEDED)}
    return {path: data for path, data in archived_files(drive).items() if path not in seeded}


def _walk(folder):
    for child in folder.iterdir():
        if child.is_dir():
            yield from _walk(child)
        else:
            yield child


@pytest.mark.asyncio
async def test_an_upload_to_a_new_month_creates_the_year_and_month_folders_and_the_file(tools, downloads, drive):
    path = _new_invoice(downloads, "hosting-2027-03.pdf", "Factuurdatum: 02-03-2027")

    result = await _upload(tools, path, "2027-03-02", f"{ARCHIVE}/2027/March/hosting-2027-03.pdf")

    assert _added(drive) == {f"{ARCHIVE}/2027/March/hosting-2027-03.pdf": path.read_bytes()}
    assert f"{ARCHIVE}/2027/March/hosting-2027-03.pdf" in result
    assert str(path.stat().st_size) in result
    assert not result.startswith("Error")


@pytest.mark.asyncio
async def test_a_different_file_under_a_taken_name_lands_under_onedrives_rename(tools, downloads, drive):
    path = _new_invoice(downloads, "kpn-factuur-123456.pdf", "A different KPN invoice")

    result = await _upload(tools, path, "2026-10-20", f"{OCTOBER}/kpn-factuur-123456 1.pdf")

    assert _added(drive) == {f"{OCTOBER}/kpn-factuur-123456 1.pdf": path.read_bytes()}
    assert archived_files(drive)[f"{OCTOBER}/kpn-factuur-123456.pdf"] == SEEDED_KPN
    assert f"{OCTOBER}/kpn-factuur-123456 1.pdf" in result


@pytest.mark.asyncio
async def test_the_same_contents_again_upload_nothing(tools, downloads, drive):
    path = downloads / "invoice-from-kpn.pdf"
    path.write_bytes(SEEDED_KPN)

    result = await _upload(tools, path, "2026-10-14", f"{OCTOBER}/invoice-from-kpn.pdf")

    assert result.startswith("NOT UPLOADED:")
    assert f"{OCTOBER}/kpn-factuur-123456.pdf" in result.splitlines()[0]
    assert _added(drive) == {}


@pytest.mark.asyncio
async def test_an_upload_twice_lands_once_and_then_reports_not_uploaded(tools, downloads, drive):
    path = _new_invoice(downloads, "hosting.pdf", "Hosting")
    target = f"{ARCHIVE}/2026/November/hosting.pdf"

    assert not (await _upload(tools, path, "2026-11-03", target)).startswith("Error")
    again = await _upload(tools, path, "2026-11-03", target)

    assert again.startswith("NOT UPLOADED:")
    assert list(_added(drive)) == [target]


@pytest.mark.asyncio
@pytest.mark.parametrize("name, invoice_date, target_path", [
    ("hosting.pdf", "2027-03-02", f"{ARCHIVE}/2027/April/hosting.pdf"),  # not the invoice date's month
    ("hosting.pdf", "2027-03-02", f"{ARCHIVE}/2027/March/other-name.pdf"),
    ("kpn-factuur-123456.pdf", "2026-10-20", f"{OCTOBER}/kpn-factuur-123456.pdf"),  # taken: not the rename
])
async def test_a_target_path_that_doesnt_match_is_refused_before_anything_is_created(
        tools, downloads, drive, name, invoice_date, target_path):
    path = _new_invoice(downloads, name, "Not a seeded invoice")

    result = await _upload(tools, path, invoice_date, target_path)

    assert result.startswith("Error:")
    assert "Processed check" in result
    assert _added(drive) == {}
    assert not (drive / ARCHIVE / "2027").exists()


@pytest.mark.asyncio
async def test_two_concurrent_uploads_to_a_new_month_both_land_in_one_month_folder(tools, downloads, drive):
    first = _new_invoice(downloads, "first.pdf", "First")
    second = _new_invoice(downloads, "second.pdf", "Second")

    results = await asyncio.gather(
        _upload(tools, first, "2027-05-01", f"{ARCHIVE}/2027/May/first.pdf"),
        _upload(tools, second, "2027-05-31", f"{ARCHIVE}/2027/May/second.pdf"),
    )

    assert not any(r.startswith("Error") for r in results), results
    assert _added(drive) == {f"{ARCHIVE}/2027/May/first.pdf": first.read_bytes(),
                             f"{ARCHIVE}/2027/May/second.pdf": second.read_bytes()}
    assert sorted(p.name for p in (drive / ARCHIVE).iterdir()) == ["2026", "2027"]
    assert [p.name for p in (drive / ARCHIVE / "2027").iterdir()] == ["May"]


class _Recorder(BaseCallbackHandler):
    """Every tool run a callback on the run sees (as Langfuse's handler would trace it)."""

    def __init__(self):
        self.started: list[str] = []
        self.seen: list[str] = []

    def on_tool_start(self, serialized, input_str, **kwargs):
        self.started.append(serialized.get("name", ""))
        self.seen.append(f"{serialized} {input_str} {kwargs}")

    def on_tool_end(self, output, **kwargs):
        self.seen.append(f"{output!r} {kwargs}")

    def on_tool_error(self, error, **kwargs):
        self.seen.append(f"{error!r} {kwargs}")


@pytest.mark.asyncio
async def test_no_callback_on_the_run_receives_the_upload_url(tools, downloads, drive):
    path = _new_invoice(downloads, "hosting.pdf", "Hosting")
    recorder = _Recorder()

    result = await _upload(tools, path, "2027-03-02", f"{ARCHIVE}/2027/March/hosting.pdf",
                           {"callbacks": [recorder]})

    assert not result.startswith("Error"), result
    assert "ms365_list-folder-files" in recorder.started  # the server tools it calls do inherit the run's callbacks
    assert "ms365_create-onedrive-folder" in recorder.started
    assert "ms365_create-upload-session" not in recorder.started
    assert not any("uploadUrl" in seen or UPLOAD_URL_SCHEME in seen for seen in recorder.seen)


# --- failures: reported as the upload's error, never raised (a Write action is never retried) ----

@pytest.fixture
def switch(tmp_path, monkeypatch):
    """Request it before `tools`: the stand-in's servers get the environment as it is when they load."""
    failure = FailureSwitch(tmp_path / "failure")
    for key, value in failure.env.items():
        monkeypatch.setenv(key, value)
    return failure


@pytest.mark.asyncio
async def test_logged_out_is_the_uploads_error_naming_the_login_command(switch, tools, downloads, drive):
    path = _new_invoice(downloads, "hosting.pdf", "Hosting")
    switch.set(Failure.LOGGED_OUT)

    result = await _upload(tools, path, "2027-03-02", f"{ARCHIVE}/2027/March/hosting.pdf")

    assert result.startswith("Error:")
    assert "--login" in result
    assert _added(drive) == {}


@pytest.mark.asyncio
async def test_a_transient_failure_is_the_uploads_error_not_raised(switch, tools, downloads, drive):
    path = _new_invoice(downloads, "hosting.pdf", "Hosting")
    switch.set(Failure.TRANSIENT, times=1)  # a retry would succeed: none happens

    result = await _upload(tools, path, "2027-03-02", f"{ARCHIVE}/2027/March/hosting.pdf")

    assert result.startswith("Error:")
    assert "503" in result
    assert _added(drive) == {}


@pytest.fixture
def drive_failing(monkeypatch):
    monkeypatch.setenv(DRIVE_FAILURE_ENV, "transient")


@pytest.mark.asyncio
async def test_the_drive_failure_switch_fails_the_upload_and_nothing_else(drive_failing, tools, downloads, drive):
    path = _new_invoice(downloads, "hosting.pdf", "Hosting")

    result = await _upload(tools, path, "2027-03-02", f"{ARCHIVE}/2027/March/hosting.pdf")
    mail = await tools["ms365_list-mail-messages"].ainvoke({})

    assert result.startswith("Error:")
    assert "503" in result
    assert _added(drive) == {}
    assert "Error" not in mail and "503" not in mail


@pytest.mark.asyncio
async def test_a_failed_put_is_the_uploads_error_without_the_upload_url(drive, downloads):
    seen: list[str] = []

    async def failing_put(upload_url: str, content: bytes) -> dict:
        seen.append(upload_url)
        raise RuntimeError(f"could not reach {upload_url}")

    server = replace(ms365_fixture_server(), wrappers=(upload_to_onedrive(failing_put),))
    [upload] = [t for t in await load_mcp_server(server) if t.name == "ms365_upload_to_onedrive"]
    path = _new_invoice(downloads, "hosting.pdf", "Hosting")

    result = await upload.ainvoke({"path": str(path), "invoice_date": "2027-03-02",
                                   "target_path": f"{ARCHIVE}/2027/March/hosting.pdf"})

    assert result.startswith("Error:")
    assert seen and seen[0] not in result
    assert _added(drive) == {}


# --- the stand-in's drive write tools, called directly (the agent binds neither) -------------

async def _stand_in(name: str, args: dict):
    result = await create_server().call_tool(name, args)
    return result.isError, "".join(block.text for block in result.content)


async def _october_id() -> str:
    _, text = await _stand_in("list-drives", {})
    item_id = "root"
    for name in [*ARCHIVE.split("/"), "2026", "October"]:
        _, text = await _stand_in("list-folder-files", {"driveId": DRIVE_ID, "driveItemId": item_id})
        [item_id] = [i["id"] for i in json.loads(text)["value"] if i["name"] == name]
    return item_id


@pytest.mark.asyncio
async def test_the_drive_write_tools_take_the_pinned_servers_arguments():
    listed = {tool.name: tool for tool in await create_server().list_tools()}

    for name in ("create-onedrive-folder", "create-upload-session"):
        schema = listed[name].inputSchema
        assert set(schema["properties"]) == {"driveId", "driveItemId", "body", "includeHeaders", "excludeResponse",
                                             "confirm"}
        assert set(schema["required"]) == {"driveId", "driveItemId", "body"}
        assert not listed[name].annotations.readOnlyHint


@pytest.mark.asyncio
async def test_an_upload_session_with_a_name_in_its_item_is_refused_as_graph_does(drive):
    failed, text = await _stand_in("create-upload-session", {
        "driveId": DRIVE_ID, "driveItemId": f"{await _october_id()}:/new.pdf:",
        "body": {"item": {"name": "new.pdf", "@microsoft.graph.conflictBehavior": "rename"}},
    })

    assert failed and "400" in text and "invalidRequest" in text


@pytest.mark.asyncio
async def test_an_existing_folder_with_conflict_behavior_fail_is_a_409_name_already_exists(drive):
    failed, text = await _stand_in("create-onedrive-folder", {
        "driveId": DRIVE_ID, "driveItemId": await _october_id(),
        "body": {"name": "nested", "folder": {}, "@microsoft.graph.conflictBehavior": "fail"},
    })
    again_failed, again = await _stand_in("create-onedrive-folder", {
        "driveId": DRIVE_ID, "driveItemId": await _october_id(),
        "body": {"name": "NESTED", "folder": {}, "@microsoft.graph.conflictBehavior": "fail"},
    })

    assert not failed and json.loads(text)["name"] == "nested"
    assert again_failed and "409" in again and "nameAlreadyExists" in again


# --- the real PUT, against httpx.MockTransport (no socket) ------------------------------------

UPLOAD_URL = "https://fixture-my.sharepoint.com/personal/jendo/_api/v2.0/drive/items/01X/uploadSession?guid=abc&tempauth=SECRET"
PDF = b"%PDF-1.4 a small invoice"


def _log_everything(caplog):
    """Capture every log record, httpx's request lines (INFO, naming the URL) included."""
    caplog.set_level(logging.DEBUG)
    caplog.set_level(logging.DEBUG, logger="httpx")
    caplog.set_level(logging.DEBUG, logger="httpcore")


def _transport(requests: list[httpx.Request], put_answer):
    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "PUT":
            return put_answer(request)
        return httpx.Response(204)
    return httpx.MockTransport(handle)


@pytest.mark.asyncio
async def test_the_put_sends_the_whole_file_in_one_range_without_authorization(caplog):
    requests: list[httpx.Request] = []
    created = {"id": "01NEW", "name": "hosting.pdf", "size": len(PDF), "file": {"hashes": {"quickXorHash": "x"}}}
    _log_everything(caplog)

    item = await httpx_put(UPLOAD_URL, PDF, transport=_transport(requests, lambda r: httpx.Response(201, json=created)))

    assert item == created
    [put] = requests
    assert put.method == "PUT" and str(put.url) == UPLOAD_URL
    assert put.content == PDF
    assert put.headers["Content-Range"] == f"bytes 0-{len(PDF) - 1}/{len(PDF)}"
    assert put.headers["Content-Length"] == str(len(PDF))
    assert "Authorization" not in put.headers
    assert "SECRET" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("put_answer", [
    lambda r: httpx.Response(500, json={"error": {"code": "generalException", "message": "An error occurred"}}),
    lambda r: (_ for _ in ()).throw(httpx.ConnectError(f"could not connect to {r.url}", request=r)),
], ids=["graph-error", "connection-error"])
async def test_a_failed_put_deletes_the_session_and_never_names_the_upload_url(caplog, put_answer):
    requests: list[httpx.Request] = []
    _log_everything(caplog)

    with pytest.raises(UploadFailed) as failed:
        await httpx_put(UPLOAD_URL, PDF, transport=_transport(requests, put_answer))

    assert [(r.method, str(r.url)) for r in requests] == [("PUT", UPLOAD_URL), ("DELETE", UPLOAD_URL)]
    assert "SECRET" not in str(failed.value)
    assert failed.value.__cause__ is None and failed.value.__context__ is None
    assert "SECRET" not in caplog.text
