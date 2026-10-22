# tests/informer_server/test_trial_balance.py
"""The trial-balance tool over Informer's column-balance report (proef- en saldibalans).

Expected figures are worked by hand from the seeded journal in
`fixture_world/data/informer/ledger_movements.json`."""

import pytest


def ledger(
    number,
    description,
    opening=("0.00", "0.00"),
    movements=("0.00", "0.00"),
    balance=("0.00", "0.00"),
    rgs_code=None,
):
    return {
        "number": number, "description": description, "rgs_code": rgs_code,
        "opening_debit": opening[0], "opening_credit": opening[1],
        "debit": movements[0], "credit": movements[1],
        "balance_debit": balance[0], "balance_credit": balance[1],
    }


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
    assert report["ledgers"] == [
        ledger("1100", "Bank", movements=("1210.00", "49.99"), balance=("1160.01", "0.00")),
        ledger("1300", "Debiteuren", opening=("500.00", "0.00"), movements=("1210.00", "1210.00"),
               balance=("500.00", "0.00")),
        ledger("1500", "BTW af te dragen 21%", movements=("0.00", "500.00"), balance=("0.00", "500.00"),
               rgs_code="BSchBepBtwOla"),
        ledger("1520", "Voorbelasting", movements=("400.00", "0.00"), balance=("400.00", "0.00"),
               rgs_code="BVorVbkTvo"),
        ledger("1542", "BTW export buiten EU"),
        ledger("1543", "BTW export buiten EU voorbelasting", rgs_code="BSchBepBtwOlb"),
        ledger("1551", "BTW Voorgaande jaren", opening=("36.69", "0.00"), balance=("36.69", "0.00"),
               rgs_code="BSchBepBtwAfo"),
        ledger("1800", "Af te dragen btw", movements=("0.00", "210.00"), balance=("0.00", "210.00")),
        ledger("4500", "Softwarekosten", movements=("49.99", "0.00"), balance=("49.99", "0.00")),
        ledger("8000", "Omzet dienstverlening", movements=("0.00", "1000.00"), balance=("0.00", "1000.00"),
               rgs_code="WOmzNohOlh"),
    ]


@pytest.mark.asyncio
async def test_opening_balance_is_the_years_whatever_the_period_range(connect, call_tool):
    async with connect() as session:
        _, report = await call_tool(session, "trial_balance", year=2026, period_from=3, period_to=3)

    debtors = next(row for row in report["ledgers"] if row["number"] == "1300")
    assert debtors == ledger("1300", "Debiteuren", opening=("500.00", "0.00"), movements=("13310.00", "1210.00"),
                             balance=("12600.00", "0.00"))


@pytest.mark.asyncio
async def test_float_noise_in_informer_amounts_becomes_exact_cents(connect, call_tool, fake_informer):
    # 0.1 + 0.2 summed in floats is 0.30000000000000004, as live Informer sums do.
    fake_informer.ledger_movements += [
        {"year": 2026, "period": 4, "ledger_number": "4500", "description": "a", "debit": "0.10", "credit": "0.00"},
        {"year": 2026, "period": 4, "ledger_number": "4500", "description": "b", "debit": "0.20", "credit": "0.00"},
    ]
    async with connect() as session:
        _, report = await call_tool(session, "trial_balance", year=2026, period_from=4, period_to=4)

    software = next(row for row in report["ledgers"] if row["number"] == "4500")
    assert software == ledger("4500", "Softwarekosten", movements=("0.30", "0.00"), balance=("0.30", "0.00"))


@pytest.mark.asyncio
async def test_trial_balance_can_be_limited_to_a_ledger_range(connect, call_tool):
    async with connect() as session:
        _, report = await call_tool(
            session, "trial_balance", year=2025, period_from=1, period_to=13, ledger_from=8000, ledger_to=8999
        )

    assert report["ledgers"] == [
        ledger("8100", "Omzet licenties", movements=("0.00", "500.00"), balance=("0.00", "500.00")),
    ]


@pytest.mark.asyncio
async def test_ledger_range_without_ledgers_is_an_empty_trial_balance(connect, call_tool):
    async with connect() as session:
        is_error, report = await call_tool(session, "trial_balance", year=2026, ledger_from=9000, ledger_to=9999)

    assert not is_error
    assert report["ledgers"] == []


@pytest.mark.asyncio
async def test_whole_year_is_the_default_period_range(connect, call_tool):
    async with connect() as session:
        _, report = await call_tool(session, "trial_balance", year=2026)

    assert (report["period_from"], report["period_to"]) == (1, 13)
    assert ledger("4000", "Huisvestingskosten", movements=("1250.00", "0.00"), balance=("1250.00", "0.00")) \
        in report["ledgers"]


@pytest.mark.asyncio
@pytest.mark.parametrize("period_from, period_to", [(0, 3), (1, 14), (5, 4)])
async def test_invalid_period_range_is_a_tool_error(connect, call_tool, period_from, period_to):
    async with connect() as session:
        is_error, text = await call_tool(
            session, "trial_balance", year=2026, period_from=period_from, period_to=period_to
        )

    assert is_error
    assert "1" in text and "13" in text
