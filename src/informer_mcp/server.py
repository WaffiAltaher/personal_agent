# src/informer_mcp/server.py
"""The Informer MCP server: read-only tools over Informer API v2 (no write endpoints, ADR-006)."""

import json
import re
from decimal import Decimal
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from informer_mcp.client import InformerClient, RateLimiter
from informer_mcp.config import InformerSettings
from informer_mcp.sales import register_sales_tools

READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True)

LAST_PERIOD = 13  # periods 1-12 plus the year-end closing period
LAST_LEDGER_NUMBER = 99999999
DUTCH_AMOUNT = re.compile(r"-?\d{1,3}(?:\.\d{3})*,\d{2}|-?\d+,\d{2}")

def _person_name(*parts: str | None) -> str:
    return " ".join(p for p in parts if p)


def _relation(raw: dict) -> dict:
    """The fields of an Informer Relation a model needs, under readable names."""
    if raw["relation_type"] == 0:
        name = raw["company_name"]
    else:
        name = _person_name(raw.get("firstname"), raw.get("surname_prefix"), raw.get("surname"))
    address = _person_name(raw.get("street"), raw.get("house_number"), raw.get("house_number_suffix"))
    return {
        "id": raw["id"],
        "relation_number": raw["relation_number"],
        "name": name,
        "email": raw.get("email"),
        "email_invoice": raw.get("email_invoice"),
        "phone": raw.get("phone"),
        "address": address,
        "zip": raw.get("zip"),
        "city": raw.get("city"),
        "country": raw.get("country"),
        "contacts": [
            {
                "name": _person_name(c.get("firstname"), c.get("surname_prefix"), c.get("surname")),
                "function": c.get("function"),
                "email": c.get("email"),
            }
            for c in raw.get("contacts", [])
        ],
    }


def _administration(raw: dict) -> dict:
    """The administration (ITtopia's own company) details, under readable names."""
    return {
        "name": raw["company_name"],
        "contact": raw.get("contact"),
        "address": _person_name(raw.get("address"), raw.get("house_number"), raw.get("house_number_suffix")),
        "zip": raw.get("zip"),
        "city": raw.get("city"),
        "country": raw.get("country"),
        "email": raw.get("email"),
        "phone": raw.get("phone_number"),
        "web": raw.get("web"),
        "coc": raw.get("coc"),
        "vat": raw.get("vat"),
        "iban": raw.get("iban"),
        "bic": raw.get("bic"),
    }


def _ledger(raw: dict) -> dict:
    """One ledger account of the chart of accounts."""
    return {
        "number": raw["number"],
        "description": raw["description"],
        "type": raw.get("type"),
        "category": raw.get("category"),
        "vat_code": raw.get("vat_code"),
        # The spec says "0" or "1"; its own example shows a boolean.
        "blocked": raw.get("blocked") in (True, 1, "1"),
    }


def _report_text(text: str) -> str:
    """A report cell as the model should see it: Dutch-notation amounts ("12.100,50")
    become exact decimal strings ("12100.50"); any other text is kept as is."""
    if DUTCH_AMOUNT.fullmatch(text.strip()):
        return str(Decimal(text.strip().replace(".", "").replace(",", ".")))
    return text


def create_server(settings: InformerSettings, rate_limiter: RateLimiter | None = None) -> FastMCP:
    informer = InformerClient(settings, rate_limiter)
    mcp = FastMCP(
        "informer",
        instructions=(
            "Read-only access to ITtopia's Informer accounting. A Relation is any party "
            "recorded in Informer, customer or supplier alike."
        ),
    )

    @mcp.tool(annotations=READ_ONLY)
    async def list_relations(search: str = "") -> dict:
        """List Relations (customers and suppliers alike). `search` matches name, email,
        city, zip code, street or Chamber of Commerce number partially, and the relation
        number exactly when numeric. Leave it empty to list all Relations."""
        params = {}
        if search:
            params["search"] = search
        paged = await informer.get_pages("/relations", "relations", params)
        return {"relations": [_relation(r) for r in paged.items], **paged.notice("relations")}

    @mcp.tool(annotations=READ_ONLY)
    async def get_relation(relation_id: int) -> dict:
        """Get one Relation by its Informer id (the `id` from list_relations)."""
        return _relation(await informer.get(f"/relations/{relation_id}"))

    register_sales_tools(mcp, informer, settings, READ_ONLY, _relation)

    @mcp.tool(annotations=READ_ONLY)
    async def trial_balance(
        year: int,
        period_from: int = 1,
        period_to: int = LAST_PERIOD,
        ledger_from: int = 1,  # Informer rejects 0 as a missing ledger_number_from
        ledger_to: int = LAST_LEDGER_NUMBER,
    ) -> dict:
        """Trial balance (proef- en saldibalans) for a year and a range of periods, in EUR.
        Periods run 1-13 (13 is the year-end closing period); the default is the whole year.
        `ledger_from`/`ledger_to` limit it to a range of ledger account numbers (see the
        chart of accounts resource). Each row is a list of columns as Informer reports them,
        with amounts converted to decimal strings; the first row names the columns."""
        if not 1 <= period_from <= period_to <= LAST_PERIOD:
            raise ValueError(
                f"Periods must run from 1 to {LAST_PERIOD}, with period_from <= period_to "
                f"(got {period_from} to {period_to})."
            )
        data = await informer.get("/reports/column-balance", {
            "year": year,
            "period_from": period_from,
            "period_to": period_to,
            "ledger_number_from": ledger_from,
            "ledger_number_to": ledger_to,
        })
        report = data["column_balance"]
        rows = [[_report_text(c["text"]) for c in report[key]["columns"]] for key in sorted(report, key=int)]
        return {"year": year, "period_from": period_from, "period_to": period_to, "currency": "EUR", "rows": rows}

    @mcp.resource("informer://administration", name="administration", mime_type="application/json")
    async def administration() -> str:
        """ITtopia's own company details in Informer: name, address, contact details,
        Chamber of Commerce and VAT numbers, and the bank account clients pay into."""
        return json.dumps(_administration(await informer.get("/administration")))

    @mcp.resource("informer://ledgers", name="ledgers", mime_type="application/json")
    async def ledgers() -> str:
        """The chart of accounts: every ledger account's number, description, type
        (balance, revenue, costs), category, VAT code and whether it is blocked."""
        return json.dumps({"ledgers": [_ledger(raw) for raw in await informer.get("/ledgers")]})

    @mcp.prompt()
    def payment_reminder(
        client_name: Annotated[str, Field(description="The Client's name, as in Informer.")],
        overdue_invoices: Annotated[str, Field(
            description="The Client's Overdue invoices, as text or JSON: number, due date (ISO) "
                        "and open amount (EUR decimal string) of each."
        )],
        contact_name: Annotated[str, Field(description="The person to address, if known.")] = "",
    ) -> str:
        """Draft a Payment reminder asking a Client to pay their Overdue invoices."""
        addressee = contact_name or client_name
        return (
            f"Write a Payment reminder to {client_name} as an email Draft for the owner to "
            "review. Never send it.\n\n"
            f"Address it to {addressee}. Keep the tone polite, factual and friendly: assume an "
            "oversight, not bad faith.\n"
            "List each Overdue invoice with its invoice number, due date and open amount in EUR, "
            "and state the total open amount. Ask them to pay it promptly, and to let us know if "
            "they have already paid or disagree with an invoice. Give ITtopia's bank account "
            "(IBAN) to pay into, from the informer://administration resource, and sign off as "
            "ITtopia.\n\n"
            f"Overdue invoices of {client_name}:\n{overdue_invoices.strip()}"
        )

    return mcp


def main() -> None:
    """Run the server over stdio, configured from INFORMER_* environment variables."""
    create_server(InformerSettings()).run("stdio")
