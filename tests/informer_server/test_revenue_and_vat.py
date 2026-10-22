# tests/informer_server/test_revenue_and_vat.py
"""Exact Revenue and VAT-to-pay tools over the fake Informer column-balance report.

Expected amounts are worked by hand from the seeded journal in
`fixture_world/data/informer/ledger_movements.json`."""

import pytest


@pytest.mark.asyncio
async def test_revenue_tools_are_read_only(connect):
    async with connect() as session:
        listed = await session.list_tools()

    for name in ("revenue", "vat_position"):
        tool = next(t for t in listed.tools if t.name == name)
        assert tool.annotations.readOnlyHint


@pytest.mark.asyncio
async def test_trial_balance_description_mentions_year_to_date_for_balance_ledgers(connect):
    async with connect() as session:
        listed = await session.list_tools()

    tool = next(t for t in listed.tools if t.name == "trial_balance")
    assert "year-to-date" in tool.description.lower()
    assert "balance-sheet" in tool.description.lower()


@pytest.mark.asyncio
async def test_balance_sheet_trial_balance_ignores_period_from(connect, call_tool):
    async with connect() as session:
        _, report = await call_tool(session, "trial_balance", year=2026, period_from=3, period_to=3)

    debtors = next(row for row in report["ledgers"] if row["number"] == "1300")
    assert debtors["debit"] == "13310.00"
    assert debtors["credit"] == "1210.00"


@pytest.mark.asyncio
async def test_revenue_for_a_sub_range_of_periods(connect, call_tool):
    async with connect() as session:
        _, result = await call_tool(session, "revenue", year=2026, period_from=1, period_to=2)

    assert result == {
        "year": 2026,
        "period_from": 1,
        "period_to": 2,
        "currency": "EUR",
        "amount": "1000.00",
        "ledgers": ["8000"],
    }


@pytest.mark.asyncio
async def test_revenue_for_another_sub_range(connect, call_tool):
    async with connect() as session:
        _, result = await call_tool(session, "revenue", year=2026, period_from=4, period_to=6)

    assert result["amount"] == "2500.00"


@pytest.mark.asyncio
async def test_revenue_for_the_full_year(connect, call_tool):
    async with connect() as session:
        _, result = await call_tool(session, "revenue", year=2026, period_from=1, period_to=13)

    assert result["amount"] == "13500.00"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("year", "quarter", "amount"),
    [
        (2026, 1, "100.00"),
        (2026, 2, "100.00"),
        (2026, 3, "-375.00"),
    ],
)
async def test_vat_to_pay_for_open_year_quarters(connect, call_tool, year, quarter, amount):
    async with connect() as session:
        _, result = await call_tool(session, "vat_position", year=year, quarter=quarter)

    assert result["currency"] == "EUR"
    assert result["amount"] == amount
    assert result["vat_charged_ledgers"] == ["1500", "1542"]
    assert result["vat_paid_ledgers"] == ["1520", "1543"]


@pytest.mark.asyncio
async def test_vat_quarter_differs_from_naive_period_range_on_balance_ledgers(connect, call_tool):
    """A quarter's VAT is not what you get by reading periods 4-6 on balance-sheet ledgers."""
    async with connect() as session:
        _, tb = await call_tool(session, "trial_balance", year=2026, period_from=4, period_to=6)
        _, vat = await call_tool(session, "vat_position", year=2026, quarter=2)

    charged = next(row for row in tb["ledgers"] if row["number"] == "1500")
    paid = next(row for row in tb["ledgers"] if row["number"] == "1520")
    naive = (
        float(charged["credit"]) - float(charged["debit"])
        - (float(paid["debit"]) - float(paid["credit"]))
    )
    assert vat["amount"] == "100.00"
    assert f"{naive:.2f}" == "200.00"


@pytest.mark.asyncio
async def test_vat_quarter_can_be_negative(connect, call_tool):
    async with connect() as session:
        _, result = await call_tool(session, "vat_position", year=2025, quarter=3)

    assert result["amount"] == "-1000.00"


@pytest.mark.asyncio
async def test_vat_includes_corrections_on_both_sides(connect, call_tool):
    async with connect() as session:
        _, q1 = await call_tool(session, "vat_position", year=2025, quarter=1)
        _, q2 = await call_tool(session, "vat_position", year=2025, quarter=2)

    assert q1["amount"] == "550.00"
    assert q2["amount"] == "413.31"


@pytest.mark.asyncio
async def test_reverse_charge_pair_cancels_in_vat_position(connect, call_tool):
    async with connect() as session:
        _, result = await call_tool(session, "vat_position", year=2025, quarter=1)

    assert result["amount"] == "550.00"


@pytest.mark.asyncio
async def test_q4_of_closed_year_is_refused(connect, call_tool):
    async with connect() as session:
        is_error, text = await call_tool(session, "vat_position", year=2025, quarter=4)

    assert is_error
    assert "2025 is closed in Informer" in text
    assert "Q4 return" in text


@pytest.mark.asyncio
async def test_q1_through_q3_of_closed_year_still_answer(connect, call_tool):
    async with connect() as session:
        _, q1 = await call_tool(session, "vat_position", year=2025, quarter=1)
        _, q3 = await call_tool(session, "vat_position", year=2025, quarter=3)

    assert q1["amount"] == "550.00"
    assert q3["amount"] == "-1000.00"


@pytest.mark.asyncio
@pytest.mark.parametrize("period_from, period_to", [(0, 3), (1, 14), (5, 4)])
async def test_invalid_revenue_period_range_is_refused(connect, call_tool, period_from, period_to):
    async with connect() as session:
        is_error, text = await call_tool(
            session, "revenue", year=2026, period_from=period_from, period_to=period_to
        )

    assert is_error
    assert "1" in text and "13" in text


@pytest.mark.asyncio
@pytest.mark.parametrize("quarter", [0, 5])
async def test_invalid_vat_quarter_is_refused(connect, call_tool, quarter):
    async with connect() as session:
        is_error, text = await call_tool(session, "vat_position", year=2026, quarter=quarter)

    assert is_error
    assert "Quarter" in text
