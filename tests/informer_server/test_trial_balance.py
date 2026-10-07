# tests/informer_server/test_trial_balance.py
"""The trial-balance tool over Informer's column-balance report (proef- en saldibalans).

Expected figures are worked by hand from the seeded journal in
`fixture_world/data/informer/ledger_movements.json`."""

import pytest

HEADER = ["Rekening", "Omschrijving", "Debet", "Credit", "Saldo debet", "Saldo credit"]


@pytest.mark.asyncio
async def test_trial_balance_tool_is_read_only(connect):
    async with connect() as session:
        listed = await session.list_tools()

    tool = next(t for t in listed.tools if t.name == "trial_balance")
    assert tool.annotations.readOnlyHint


@pytest.mark.asyncio
async def test_trial_balance_for_a_period_range(connect, call_tool):
    async with connect() as session:
        is_error, report = await call_tool(session, "trial_balance", year=2026, period_from=1, period_to=2)

    assert not is_error
    assert (report["year"], report["period_from"], report["period_to"], report["currency"]) == (2026, 1, 2, "EUR")
    assert report["rows"] == [
        HEADER,
        ["1100", "Bank", "1210.00", "49.99", "1160.01", "0.00"],
        ["1300", "Debiteuren", "1210.00", "1210.00", "0.00", "0.00"],
        ["1800", "Af te dragen btw", "0.00", "210.00", "0.00", "210.00"],
        ["4500", "Softwarekosten", "49.99", "0.00", "49.99", "0.00"],
        ["8000", "Omzet dienstverlening", "0.00", "1000.00", "0.00", "1000.00"],
        ["", "Totaal", "2469.99", "2469.99", "1210.00", "1210.00"],
    ]


@pytest.mark.asyncio
async def test_amounts_with_thousands_separators_become_plain_decimal_strings(connect, call_tool):
    async with connect() as session:
        _, report = await call_tool(session, "trial_balance", year=2026, period_from=1, period_to=3)

    debtors = next(row for row in report["rows"] if row[0] == "1300")
    assert debtors == ["1300", "Debiteuren", "13310.00", "1210.00", "12100.00", "0.00"]


@pytest.mark.asyncio
async def test_trial_balance_can_be_limited_to_a_ledger_range(connect, call_tool):
    async with connect() as session:
        _, report = await call_tool(
            session, "trial_balance", year=2025, period_from=1, period_to=13, ledger_from=8000, ledger_to=8999
        )

    assert report["rows"] == [
        HEADER,
        ["8100", "Omzet licenties", "0.00", "500.00", "0.00", "500.00"],
        ["", "Totaal", "0.00", "500.00", "0.00", "500.00"],
    ]


@pytest.mark.asyncio
async def test_whole_year_is_the_default_period_range(connect, call_tool):
    async with connect() as session:
        _, report = await call_tool(session, "trial_balance", year=2026)

    assert (report["period_from"], report["period_to"]) == (1, 13)
    assert ["4000", "Huisvestingskosten", "1250.00", "0.00", "1250.00", "0.00"] in report["rows"]


@pytest.mark.asyncio
@pytest.mark.parametrize("period_from, period_to", [(0, 3), (1, 14), (5, 4)])
async def test_invalid_period_range_is_a_tool_error(connect, call_tool, period_from, period_to):
    async with connect() as session:
        is_error, text = await call_tool(
            session, "trial_balance", year=2026, period_from=period_from, period_to=period_to
        )

    assert is_error
    assert "1" in text and "13" in text
