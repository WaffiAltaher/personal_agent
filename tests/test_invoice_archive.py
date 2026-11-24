"""
tests/test_invoice_archive.py

Listing the Invoice archive (ADR-020). Two seams:
- the MS365 stand-in's drive tools (`list-drives`, `list-folder-files`), called directly: the
  agent never binds them, so their shapes are pinned here against the pinned server's listing;
- `ms365_list_invoice_archive`, exactly as `load_all_tools(fixtures=True)` binds it, invoked
  directly over a seeded drive directory in a temporary folder. Nothing reaches a real OneDrive.
"""

import json

import pytest
import pytest_asyncio
from mcp.types import CallToolResult

from agent.tools import load_all_tools
from agent.tools.classification import is_read
from fixture_world.ms365 import DRIVE_ENV, Failure, FailureSwitch, create_server


@pytest.fixture
def drive(tmp_path, monkeypatch):
    """The stand-in's drive directory: seeded from the Fixture world on first use."""
    path = tmp_path / "drive"
    monkeypatch.setenv(DRIVE_ENV, str(path))
    return path


@pytest.fixture
def switch(tmp_path, monkeypatch):
    """A failure switch the stand-in's processes read: request it before `tools`, whose servers
    get the environment as it is when they load."""
    failure = FailureSwitch(tmp_path / "failure")
    for key, value in failure.env.items():
        monkeypatch.setenv(key, value)
    return failure


async def _call_stand_in(name: str, args: dict) -> CallToolResult:
    return await create_server().call_tool(name, args)


def _body(result: CallToolResult):
    return json.loads("".join(block.text for block in result.content))


async def _children(drive_id: str, item_id: str, **options) -> list[dict]:
    result = await _call_stand_in("list-folder-files", {"driveId": drive_id, "driveItemId": item_id, **options})
    assert not result.isError, result
    return _body(result)["value"]


async def _drive_id() -> str:
    [found] = _body(await _call_stand_in("list-drives", {}))["value"]
    return found["id"]


async def _walk(*names: str) -> tuple[str, str]:
    """(drive id, item id) of the folder at `names` below the drive's root."""
    drive_id, item_id = await _drive_id(), "root"
    for name in names:
        [item_id] = [i["id"] for i in await _children(drive_id, item_id) if i["name"] == name]
    return drive_id, item_id


# --- the stand-in's drive tools -------------------------------------------------------------

# The input parameters of the pinned server's tools (@softeria/ms-365-mcp-server@0.159.1), from
# its tool listing: path parameters by name, OData options without the `$`, and the options the
# server adds to every Graph GET tool.
_LIST_OPTIONS = {"top", "skip", "search", "filter", "count", "orderby", "select", "expand",
                 "fetchAllPages", "skiptoken", "includeHeaders", "excludeResponse"}


@pytest.mark.asyncio
async def test_the_drive_tools_take_the_pinned_servers_arguments():
    listed = {tool.name: tool for tool in await create_server().list_tools()}

    assert set(listed["list-drives"].inputSchema["properties"]) == _LIST_OPTIONS
    folder_files = listed["list-folder-files"].inputSchema
    assert set(folder_files["properties"]) == _LIST_OPTIONS | {"driveId", "driveItemId"}
    assert set(folder_files["required"]) == {"driveId", "driveItemId"}
    assert listed["list-drives"].annotations.readOnlyHint
    assert listed["list-folder-files"].annotations.readOnlyHint


@pytest.mark.asyncio
async def test_list_drives_returns_the_one_business_drive(drive):
    [found] = _body(await _call_stand_in("list-drives", {}))["value"]

    assert found["driveType"] == "business"
    assert found["id"]


@pytest.mark.asyncio
async def test_the_seeded_drive_holds_october_2026_purchase_invoices_with_stable_ids(drive):
    drive_id, october = await _walk("Documents", "ittopia", "admin", "2026", "October")

    files = await _children(drive_id, october)

    assert sorted(f["name"] for f in files) == ["CH-2026-1044.pdf", "kpn-factuur-123456.pdf"]
    assert all(f["size"] > 0 and "file" in f and "folder" not in f for f in files)
    assert (await _walk("Documents", "ittopia", "admin", "2026", "October"))[1] == october  # stable


@pytest.mark.asyncio
async def test_folders_carry_a_folder_facet_and_select_trims_the_fields(drive):
    drive_id = await _drive_id()

    [documents] = await _children(drive_id, "root", select="name,folder")

    assert documents == {"id": documents["id"], "name": "Documents", "folder": {"childCount": 1}}


@pytest.mark.asyncio
async def test_an_unknown_item_is_graphs_404(drive):
    result = await _call_stand_in("list-folder-files", {"driveId": await _drive_id(), "driveItemId": "nope"})

    assert result.isError
    assert "Microsoft Graph API error: 404" in _body(result)["error"]


@pytest.mark.asyncio
async def test_the_drive_tools_fail_as_switched(drive, switch):
    switch.set(Failure.LOGGED_OUT)

    result = await _call_stand_in("list-drives", {})

    assert result.isError
    assert "No valid token found" in _body(result)["error"]


# --- ms365_list_invoice_archive, as the agent binds it ----------------------------------------

@pytest_asyncio.fixture
async def tools(drive):
    tools, notices = await load_all_tools(fixtures=True)
    assert notices == []
    return {t.name: t for t in tools}


async def _list_archive(tools, **args) -> str:
    return await tools["ms365_list_invoice_archive"].ainvoke(args)


@pytest.mark.asyncio
async def test_the_archive_listing_is_bound_as_a_read_and_the_drive_tools_are_not(tools):
    assert is_read(tools["ms365_list_invoice_archive"])
    assert "ms365_list-drives" not in tools
    assert "ms365_list-folder-files" not in tools
    assert "names" in tools["ms365_list_invoice_archive"].description.lower()


@pytest.mark.asyncio
async def test_a_seeded_month_lists_its_file_names_and_sizes(tools):
    result = await _list_archive(tools, year=2026, month=10)

    assert "Documents/ittopia/admin/2026/October" in result
    assert "kpn-factuur-123456.pdf" in result and "CH-2026-1044.pdf" in result
    assert "Factuur.pdf" not in result  # September's
    assert "638" in result  # kpn-factuur-123456.pdf's size in bytes
    assert "name" in result.lower()  # says that only names were matched


@pytest.mark.asyncio
async def test_a_year_lists_its_month_folders_and_their_file_names(tools):
    result = await _list_archive(tools, year=2026)

    assert "September" in result and "October" in result
    assert "Factuur.pdf" in result and "kpn-factuur-123456.pdf" in result
    assert result.index("September") < result.index("October")  # calendar order


@pytest.mark.asyncio
async def test_folder_names_match_case_insensitively(tools, drive):
    await _list_archive(tools, year=2026)  # seeds the drive
    (drive / "Documents" / "ittopia" / "admin" / "2026" / "October").rename(
        drive / "Documents" / "ittopia" / "admin" / "2026" / "october")

    result = await _list_archive(tools, year=2026, month=10)

    assert "kpn-factuur-123456.pdf" in result


@pytest.mark.asyncio
async def test_a_missing_month_or_year_holds_nothing_and_is_not_an_error(tools):
    month = await _list_archive(tools, year=2026, month=11)
    year = await _list_archive(tools, year=2025)

    for result in (month, year):
        assert not result.startswith("Error:")
        assert "holds nothing" in result
    assert "November 2026" in month
    assert "2025" in year


@pytest.mark.asyncio
async def test_a_missing_admin_folder_is_an_error(tools, drive):
    await _list_archive(tools, year=2026)  # seeds the drive
    (drive / "Documents" / "ittopia" / "admin").rename(drive / "Documents" / "ittopia" / "archive")

    result = await _list_archive(tools, year=2026, month=10)

    assert result.startswith("Error:")
    assert "Documents/ittopia/admin" in result


@pytest.mark.asyncio
async def test_a_month_out_of_range_is_refused(tools):
    result = await _list_archive(tools, year=2026, month=13)

    assert result.startswith("Error:")


@pytest.mark.asyncio
async def test_logged_out_the_listing_names_the_login_command(switch, tools):
    switch.set(Failure.LOGGED_OUT)  # after startup, whose login check would skip the server

    result = await _list_archive(tools, year=2026, month=10)

    assert result.startswith("Error:")
    assert "--login" in result
