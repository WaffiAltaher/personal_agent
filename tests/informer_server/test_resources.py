# tests/informer_server/test_resources.py
"""The administration details and the chart of accounts, exposed as MCP resources."""

import json

import pytest
from mcp.shared.exceptions import McpError

from fixture_world.informer_api import Failure


async def read_json(session, uri: str):
    result = await session.read_resource(uri)
    return json.loads(result.contents[0].text)


@pytest.mark.asyncio
async def test_server_lists_administration_and_chart_of_accounts_resources(connect):
    async with connect() as session:
        listed = await session.list_resources()

    resources = {str(r.uri): r for r in listed.resources}
    assert set(resources) == {"informer://administration", "informer://ledgers"}
    assert all(r.mimeType == "application/json" for r in resources.values())


@pytest.mark.asyncio
async def test_administration_resource_has_company_details(connect):
    async with connect() as session:
        administration = await read_json(session, "informer://administration")

    assert administration["name"] == "ITtopia Fixture B.V."
    assert administration["address"] == "Fixtureweg 1"
    assert (administration["zip"], administration["city"], administration["country"]) == ("1011 AA", "Amsterdam", "NL")
    assert administration["email"] == "administratie@ittopia.example"
    assert administration["iban"] == "NL00FIXT0123456789"
    assert administration["vat"] == "NL001234567B01"


@pytest.mark.asyncio
async def test_chart_of_accounts_resource_lists_every_ledger(connect):
    async with connect() as session:
        chart = await read_json(session, "informer://ledgers")

    ledgers = {ledger["number"]: ledger for ledger in chart["ledgers"]}
    assert set(ledgers) == {
        "0100", "1100", "1300", "1500", "1520", "1542", "1543", "1551",
        "1600", "1800", "4000", "4500", "8000", "8100",
    }
    assert ledgers["1300"] == {
        "number": "1300",
        "description": "Debiteuren",
        "type": "balance",
        "category": "Balans",
        "vat_code": None,
        "blocked": False,
    }
    assert ledgers["8000"]["vat_code"] == "VH"
    assert ledgers["0100"]["blocked"] is True


@pytest.mark.asyncio
async def test_reading_a_resource_with_rejected_credentials_names_the_settings(fake_informer, connect):
    fake_informer.failure = Failure.UNAUTHORIZED

    async with connect() as session:
        with pytest.raises(McpError) as raised:
            await session.read_resource("informer://ledgers")

    assert "INFORMER_API_KEY" in str(raised.value)
