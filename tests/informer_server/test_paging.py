# tests/informer_server/test_paging.py
"""The server pages through Informer list endpoints itself, up to a page cap,
and says so when the cap cut a result short."""

import pytest

ALL_INVOICE_NUMBERS = ["2026-0101", "2026-0102", "2026-0103", "2026-0104", "2026-0105",
                       "2026-0098", "2026-0106", "2026-0110", "2026-0111", ""]


@pytest.mark.asyncio
async def test_reads_every_page_of_sales_invoices(fake_informer, informer_settings, connect, call_tool):
    settings = informer_settings.model_copy(update={"page_size": 3})

    async with connect(settings) as session:
        _, payload = await call_tool(session, "list_sales_invoices")

    assert [i["number"] for i in payload["invoices"]] == ALL_INVOICE_NUMBERS
    assert payload["truncated"] is False
    assert "notice" not in payload
    assert [q["page"] for path, q in fake_informer.requests] == ["0", "1", "2", "3"]


@pytest.mark.asyncio
async def test_page_cap_truncates_with_a_notice(fake_informer, informer_settings, connect, call_tool):
    settings = informer_settings.model_copy(update={"page_size": 3, "max_pages": 2})

    async with connect(settings) as session:
        _, payload = await call_tool(session, "list_sales_invoices")

    assert [i["number"] for i in payload["invoices"]] == ALL_INVOICE_NUMBERS[:6]
    assert payload["truncated"] is True
    assert "first 6 sales invoices" in payload["notice"]
    assert len(fake_informer.requests) == 2


@pytest.mark.asyncio
async def test_relations_are_paged_and_truncated_too(informer_settings, connect, call_tool):
    settings = informer_settings.model_copy(update={"page_size": 2, "max_pages": 2})

    async with connect(settings) as session:
        _, payload = await call_tool(session, "list_relations")

    assert [r["id"] for r in payload["relations"]] == [1001, 1002, 1003, 1004]
    assert payload["truncated"] is True
    assert "first 4 relations" in payload["notice"]
