# src/informer_mcp/server.py
"""The Informer MCP server: read-only tools over Informer API v2 (no write endpoints, ADR-006)."""

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from informer_mcp.client import InformerClient, RateLimiter
from informer_mcp.config import InformerSettings
from informer_mcp.sales import register_sales_tools

READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True)


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

    return mcp


def main() -> None:
    """Run the server over stdio, configured from INFORMER_* environment variables."""
    create_server(InformerSettings()).run("stdio")
