# tests/informer_server/test_sales_invoices.py
import pytest


@pytest.mark.asyncio
async def test_lists_a_relations_sales_invoices_with_decimal_amounts_and_iso_dates(connect, call_tool):
    async with connect() as session:
        is_error, payload = await call_tool(session, "list_sales_invoices", relation_id=1002)

    assert not is_error
    assert payload["currency"] == "EUR"
    assert [
        (i["number"], i["invoice_date"], i["due_date"], i["total_incl_vat"], i["paid"], i["open_amount"])
        for i in payload["invoices"]
    ] == [
        ("2026-0102", "2026-08-02", "2026-09-01", "100.10", "0.00", "100.10"),
        ("2026-0103", "2026-08-11", "2026-09-10", "200.20", "0.00", "200.20"),
        ("2026-0098", "2026-06-01", "2026-07-01", "500.00", "500.00", "0.00"),
    ]
    assert payload["truncated"] is False


@pytest.mark.asyncio
async def test_filters_sales_invoices_by_status(connect, call_tool):
    async with connect() as session:
        _, payload = await call_tool(session, "list_sales_invoices", status="open", relation_id=1002)

    assert [(i["number"], i["open_amount"]) for i in payload["invoices"]] == [
        ("2026-0102", "100.10"),
        ("2026-0103", "200.20"),
    ]


@pytest.mark.asyncio
async def test_unknown_status_is_rejected(connect, call_tool):
    async with connect() as session:
        is_error, _ = await call_tool(session, "list_sales_invoices", status="overdue")

    assert is_error


@pytest.mark.asyncio
async def test_get_sales_invoice_returns_its_lines(connect, call_tool):
    async with connect() as session:
        is_error, invoice = await call_tool(session, "get_sales_invoice", invoice_id=5005)

    assert not is_error
    assert (invoice["number"], invoice["relation_id"], invoice["due_date"]) == ("2026-0105", 1001, "2026-09-14")
    assert (invoice["total_excl_vat"], invoice["vat"], invoice["total_incl_vat"]) == ("500.00", "105.00", "605.00")
    assert (invoice["paid"], invoice["open_amount"], invoice["payment_date"]) == ("300.00", "305.00", "2026-09-20")
    assert invoice["lines"] == [
        {"description": "IT-beheer 2026-08", "quantity": "1", "unit_price": "500.00", "vat_percentage": "21"},
    ]


@pytest.mark.asyncio
async def test_unknown_sales_invoice_is_a_tool_error(connect, call_tool):
    async with connect() as session:
        is_error, text = await call_tool(session, "get_sales_invoice", invoice_id=9999)

    assert is_error
    assert "404" in text
