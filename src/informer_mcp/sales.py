# src/informer_mcp/sales.py
"""Sales invoice tools, and the Overdue invoice calculation Informer itself lacks.

Vocabulary follows GLOSSARY.md: Client, Sales invoice, Due date, Open amount, Overdue invoice.
Money leaves the server as exact decimal strings in EUR, dates as ISO strings.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from zoneinfo import ZoneInfo

from mcp.server.fastmcp import FastMCP

from informer_mcp.client import InformerClient
from informer_mcp.config import InformerSettings

ITTOPIA_TZ = ZoneInfo("Europe/Amsterdam")
CURRENCY = "EUR"
CENT = Decimal("0.01")

# Informer's own sales-invoice status filters. It has no "overdue" filter: use list_overdue_invoices.
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


def _today(settings: InformerSettings) -> date:
    return settings.today or datetime.now(ITTOPIA_TZ).date()


def _as_of_date(as_of: str | None, settings: InformerSettings) -> date:
    if not as_of:
        return _today(settings)
    try:
        return date.fromisoformat(as_of)
    except ValueError:
        raise ValueError(f"as_of must be an ISO date (YYYY-MM-DD), got {as_of!r}") from None


def _overdue(raw: dict, as_of: date) -> bool:
    """GLOSSARY.md: an Open amount greater than zero and a Due date before the as-of date."""
    if raw["concept"] == "1":  # a concept was never issued, so it is not a Sales invoice yet
        return False
    due = iso_date(raw["expiry_date"])
    return money(raw["totals"]["open"]) > 0 and due is not None and date.fromisoformat(due) < as_of


def register_sales_tools(mcp: FastMCP, informer: InformerClient, settings: InformerSettings,
                         read_only, describe_relation) -> None:
    @mcp.tool(annotations=read_only)
    async def list_sales_invoices(status: SalesInvoiceStatus | None = None, relation_id: int | None = None) -> dict:
        """List Sales invoices (invoices ITtopia issued), optionally filtered by Informer
        status ("open" = not yet fully paid, "concept" = not yet issued, ...) and/or by one
        Relation's `id`. Amounts are decimal strings in EUR; `due_date` is the Due date.
        For Overdue invoices use list_overdue_invoices instead."""
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

    @mcp.tool(annotations=read_only)
    async def list_overdue_invoices(as_of: str | None = None) -> dict:
        """List Overdue invoices: Sales invoices with an Open amount above zero whose Due
        date is before `as_of` (an ISO date, YYYY-MM-DD; default today). An invoice due on
        `as_of` itself is not overdue yet. Grouped by Client, each with its email addresses
        and total Open amount, largest total first. Open amounts are the current ones, also
        for a past `as_of`. Amounts are decimal strings in EUR."""
        as_of_date = _as_of_date(as_of, settings)
        paged = await informer.get_pages("/invoices/sales", "invoices", {"filter": "open"})
        by_client: dict[int, list[dict]] = {}
        for raw in paged.items:
            if _overdue(raw, as_of_date):
                by_client.setdefault(raw["relation_id"], []).append(raw)

        clients = []
        for relation_id, invoices in by_client.items():
            relation = describe_relation(await informer.get(f"/relations/{relation_id}"))
            invoices.sort(key=lambda raw: raw["expiry_date"])
            clients.append({
                "relation_id": relation_id,
                "name": relation["name"],
                "email": relation["email"],
                "email_invoice": relation["email_invoice"],
                "total_open_amount": sum((money(i["totals"]["open"]) for i in invoices), Decimal("0.00")),
                "invoices": [
                    {
                        "id": raw["id"],
                        "number": raw["number"],
                        "invoice_date": iso_date(raw["invoice_date"]),
                        "due_date": iso_date(raw["expiry_date"]),
                        "days_overdue": (as_of_date - date.fromisoformat(raw["expiry_date"][:10])).days,
                        "total_incl_vat": str(money(raw["totals"]["incl_vat"])),
                        "open_amount": str(money(raw["totals"]["open"])),
                    }
                    for raw in invoices
                ],
            })
        clients.sort(key=lambda c: (-c["total_open_amount"], c["name"]))
        total = sum((c["total_open_amount"] for c in clients), Decimal("0.00"))
        for client in clients:
            client["total_open_amount"] = str(client["total_open_amount"])
        return {
            "as_of": as_of_date.isoformat(),
            "currency": CURRENCY,
            "total_open_amount": str(total),
            "clients": clients,
            **paged.notice("open sales invoices"),
        }
