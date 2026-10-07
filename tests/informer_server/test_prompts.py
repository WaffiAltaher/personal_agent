# tests/informer_server/test_prompts.py
"""The Payment reminder prompt template (the third MCP primitive)."""

import json

import pytest

OVERDUE_INVOICES = json.dumps([
    {"invoice_number": "F2026-0014", "due_date": "2026-08-31", "open_amount": "1210.00"},
    {"invoice_number": "F2026-0021", "due_date": "2026-09-15", "open_amount": "250.50"},
])


@pytest.mark.asyncio
async def test_server_lists_the_payment_reminder_prompt_with_its_arguments(connect):
    async with connect() as session:
        listed = await session.list_prompts()

    prompt = next(p for p in listed.prompts if p.name == "payment_reminder")
    arguments = {a.name: a.required for a in prompt.arguments}
    assert arguments == {"client_name": True, "overdue_invoices": True, "contact_name": False}


@pytest.mark.asyncio
async def test_payment_reminder_renders_client_and_overdue_invoices(connect):
    async with connect() as session:
        rendered = await session.get_prompt("payment_reminder", {
            "client_name": "Bakkerij De Gouden Bol B.V.",
            "overdue_invoices": OVERDUE_INVOICES,
            "contact_name": "Jan de Bakker",
        })

    [message] = rendered.messages
    text = message.content.text
    assert message.role == "user"
    assert "Bakkerij De Gouden Bol B.V." in text
    assert "Jan de Bakker" in text
    assert OVERDUE_INVOICES in text
    assert "Draft" in text and "never send" in text.lower()
    assert "informer://administration" in text  # where the bank account to pay into lives


@pytest.mark.asyncio
async def test_payment_reminder_without_a_contact_addresses_the_client(connect):
    async with connect() as session:
        rendered = await session.get_prompt("payment_reminder", {
            "client_name": "Noordzee Advies",
            "overdue_invoices": "F2026-0030, due 2026-07-01, open EUR 99.00",
        })

    text = rendered.messages[0].content.text
    assert "Address it to Noordzee Advies" in text
    assert "F2026-0030, due 2026-07-01, open EUR 99.00" in text
