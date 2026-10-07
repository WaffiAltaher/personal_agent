# tests/informer_server/test_overdue_invoices.py
"""Overdue invoice (GLOSSARY.md): a Sales invoice with an Open amount greater than zero
whose Due date is before the as-of date. Seeded Fixture world, as of 2026-10-07."""

from datetime import date

import pytest


def _numbers(payload: dict) -> dict[int, list[tuple[str, str]]]:
    return {c["relation_id"]: [(i["number"], i["open_amount"]) for i in c["invoices"]] for c in payload["clients"]}


@pytest.mark.asyncio
async def test_overdue_invoices_are_grouped_by_client_with_totals(connect, call_tool):
    async with connect() as session:
        is_error, payload = await call_tool(session, "list_overdue_invoices", as_of="2026-10-07")

    assert not is_error
    assert (payload["as_of"], payload["currency"], payload["total_open_amount"]) == ("2026-10-07", "EUR", "2265.30")
    assert payload["truncated"] is False
    assert payload["clients"] == [
        {
            "relation_id": 1001,
            "name": "Bakkerij De Gouden Bol B.V.",
            "email": "administratie@goudenbol.example",
            "email_invoice": "facturen@goudenbol.example",
            "total_open_amount": "1515.00",
            "invoices": [
                {"id": 5001, "number": "2026-0101", "invoice_date": "2026-08-01", "due_date": "2026-08-31",
                 "days_overdue": 37, "total_incl_vat": "1210.00", "open_amount": "1210.00"},
                {"id": 5005, "number": "2026-0105", "invoice_date": "2026-08-15", "due_date": "2026-09-14",
                 "days_overdue": 23, "total_incl_vat": "605.00", "open_amount": "305.00"},
            ],
        },
        {
            "relation_id": 1004,
            "name": "Noordzee Advies",
            "email": None,
            "email_invoice": None,
            "total_open_amount": "450.00",
            "invoices": [
                {"id": 5004, "number": "2026-0104", "invoice_date": "2026-08-21", "due_date": "2026-09-20",
                 "days_overdue": 17, "total_incl_vat": "450.00", "open_amount": "450.00"},
            ],
        },
        {
            "relation_id": 1002,
            "name": "Van Dijk Logistiek B.V.",
            "email": "info@vandijklogistiek.example",
            "email_invoice": None,
            "total_open_amount": "300.30",  # 100.10 + 200.20, not 300.29999999999995
            "invoices": [
                {"id": 5002, "number": "2026-0102", "invoice_date": "2026-08-02", "due_date": "2026-09-01",
                 "days_overdue": 36, "total_incl_vat": "100.10", "open_amount": "100.10"},
                {"id": 5003, "number": "2026-0103", "invoice_date": "2026-08-11", "due_date": "2026-09-10",
                 "days_overdue": 27, "total_incl_vat": "200.20", "open_amount": "200.20"},
            ],
        },
    ]


@pytest.mark.asyncio
async def test_invoice_due_today_is_not_overdue_until_tomorrow(connect, call_tool):
    async with connect() as session:
        _, today = await call_tool(session, "list_overdue_invoices", as_of="2026-10-07")
        _, tomorrow = await call_tool(session, "list_overdue_invoices", as_of="2026-10-08")

    assert ("2026-0110", "242.00") not in _numbers(today)[1001]
    assert ("2026-0110", "242.00") in _numbers(tomorrow)[1001]


@pytest.mark.asyncio
async def test_past_due_invoice_with_zero_open_amount_is_not_overdue(connect, call_tool):
    async with connect() as session:
        _, payload = await call_tool(session, "list_overdue_invoices", as_of="2026-10-07")

    # 2026-0098 (Van Dijk, due 2026-07-01) and 2026-0106 (De Vries, due 2026-10-01) are fully paid.
    assert "2026-0098" not in [n for n, _ in _numbers(payload)[1002]]
    assert 1003 not in _numbers(payload)


@pytest.mark.asyncio
async def test_partially_paid_past_due_invoice_is_overdue_with_the_remaining_amount(connect, call_tool):
    async with connect() as session:
        _, payload = await call_tool(session, "list_overdue_invoices", as_of="2026-10-07")

    assert ("2026-0105", "305.00") in _numbers(payload)[1001]


@pytest.mark.asyncio
async def test_as_of_defaults_to_today(informer_settings, connect, call_tool):
    settings = informer_settings.model_copy(update={"today": date(2026, 9, 2)})

    async with connect(settings) as session:
        _, payload = await call_tool(session, "list_overdue_invoices")

    assert payload["as_of"] == "2026-09-02"
    assert _numbers(payload) == {1001: [("2026-0101", "1210.00")], 1002: [("2026-0102", "100.10")]}


@pytest.mark.asyncio
async def test_nothing_overdue_reports_an_empty_list_and_zero_total(connect, call_tool):
    async with connect() as session:
        _, payload = await call_tool(session, "list_overdue_invoices", as_of="2026-08-01")

    assert (payload["clients"], payload["total_open_amount"]) == ([], "0.00")


@pytest.mark.asyncio
async def test_as_of_must_be_an_iso_date(connect, call_tool):
    async with connect() as session:
        is_error, text = await call_tool(session, "list_overdue_invoices", as_of="07-10-2026")

    assert is_error
    assert "YYYY-MM-DD" in text
