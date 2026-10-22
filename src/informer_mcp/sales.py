# src/informer_mcp/sales.py
"""Sales invoice tools.

Vocabulary follows GLOSSARY.md: Client, Sales invoice, Due date, Open amount.
Money leaves the server as exact decimal strings in EUR, dates as ISO strings.
"""

from decimal import Decimal
from typing import Literal

from mcp.server.fastmcp import FastMCP

from informer_mcp.client import InformerClient

CURRENCY = "EUR"
CENT = Decimal("0.01")

# Informer's own sales-invoice status filters.
SalesInvoiceStatus = Literal["concept", "open", "collect", "accruals", "collection_fines", "payment_plans"]


def money(amount: float | int | str | Decimal | None) -> Decimal:
    """Informer's JSON numbers as exact euros. `str()` first, so 100.1 stays 100.10."""
    return Decimal(str(amount or 0)).quantize(CENT)


def number(value: float | int | None) -> str | None:
    """A non-money number (quantity, percentage) as an exact decimal string: 21.0 -> "21"."""
    if value is None:
        return None
    return format(Decimal(str(value)).normalize(), "f")


def iso_date(value: str | None) -> str | None:
    """Informer dates (`YYYY-mm-dd`, or a blank/zero date) as ISO dates or None."""
    if not value or value.startswith("0000"):
        return None
    return value[:10]


def _invoice(raw: dict) -> dict:
    """The fields of an Informer Sales invoice a model needs, under glossary names."""
    totals = raw["totals"]
    return {
        "id": raw["id"],
        "number": raw["number"],
        "relation_id": raw["relation_id"],
        "invoice_date": iso_date(raw["invoice_date"]),
        "due_date": iso_date(raw["expiry_date"]),
        "total_incl_vat": str(money(totals["incl_vat"])),
        "paid": str(money(totals["paid"])),
        "open_amount": str(money(totals["open"])),
        "status": raw["status"]["status"],
        "concept": raw["concept"] == "1",
        "payment_date": iso_date(raw.get("payment_date")),
    }


def _invoice_detail(raw: dict) -> dict:
    """A Sales invoice with its VAT split, reference and lines."""
    totals = raw["totals"]
    return {
        **_invoice(raw),
        "total_excl_vat": str(money(totals["excl_vat"])),
        "vat": str(money(totals["vat"])),
        "reference": raw.get("reference"),
        "reminder_status": raw.get("reminder_status"),
        "last_reminder_date": iso_date(raw.get("last_reminder_date")),
        "url": raw.get("url"),
        "lines": [
            {
                "description": line.get("description"),
                "quantity": number(line.get("qty")),
                "unit_price": None if line.get("amount") is None else str(money(line["amount"])),
                "vat_percentage": number((line.get("vat") or {}).get("percentage")),
            }
            for line in raw.get("lines", [])
        ],
    }


def register_sales_tools(mcp: FastMCP, informer: InformerClient, read_only, describe_relation) -> None:
    del describe_relation  # reserved for future Relation-enriched invoice tools

    @mcp.tool(annotations=read_only)
    async def list_sales_invoices(status: SalesInvoiceStatus | None = None, relation_id: int | None = None) -> dict:
        """List Sales invoices (invoices ITtopia issued), optionally filtered by Informer
        status ("open" = not yet fully paid, "concept" = not yet issued, ...) and/or by one
        Relation's `id`. Amounts are decimal strings in EUR; `due_date` is the Due date."""
        params: dict = {}
        if status:
            params["filter"] = status
        if relation_id is not None:
            params["relation_id"] = relation_id
        paged = await informer.get_pages("/invoices/sales", "invoices", params)
        return {
            "currency": CURRENCY,
            "invoices": [_invoice(i) for i in paged.items],
            **paged.notice("sales invoices"),
        }

    @mcp.tool(annotations=read_only)
    async def get_sales_invoice(invoice_id: int) -> dict:
        """Get one Sales invoice by its Informer id (the `id` from list_sales_invoices),
        including its lines. Amounts are decimal strings in EUR."""
        return {"currency": CURRENCY, **_invoice_detail(await informer.get(f"/invoices/sales/{invoice_id}"))}
