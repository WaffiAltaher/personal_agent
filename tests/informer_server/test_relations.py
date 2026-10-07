# tests/informer_server/test_relations.py
import pytest


@pytest.mark.asyncio
async def test_server_exposes_read_only_relation_tools(connect):
    async with connect() as session:
        listed = await session.list_tools()

    tools = {t.name: t for t in listed.tools}
    assert set(tools) == {"list_relations", "get_relation"}
    assert all(t.annotations and t.annotations.readOnlyHint for t in tools.values())


@pytest.mark.asyncio
async def test_search_finds_relation_with_its_email_address(connect, call_tool):
    async with connect() as session:
        is_error, payload = await call_tool(session, "list_relations", search="logistiek")

    assert not is_error
    assert [(r["id"], r["name"], r["email"]) for r in payload["relations"]] == [
        (1002, "Van Dijk Logistiek B.V.", "info@vandijklogistiek.example"),
    ]


@pytest.mark.asyncio
async def test_private_relation_is_named_after_the_person(connect, call_tool):
    async with connect() as session:
        _, payload = await call_tool(session, "list_relations", search="vries")

    assert [r["name"] for r in payload["relations"]] == ["Sanne de Vries"]


@pytest.mark.asyncio
async def test_listing_without_search_returns_every_relation(connect, call_tool):
    async with connect() as session:
        _, payload = await call_tool(session, "list_relations")

    assert {r["id"] for r in payload["relations"]} == {1001, 1002, 1003, 1004, 2001}


@pytest.mark.asyncio
async def test_get_relation_returns_contact_details(connect, call_tool):
    async with connect() as session:
        is_error, relation = await call_tool(session, "get_relation", relation_id=1001)

    assert not is_error
    assert relation["name"] == "Bakkerij De Gouden Bol B.V."
    assert relation["email"] == "administratie@goudenbol.example"
    assert relation["email_invoice"] == "facturen@goudenbol.example"
    assert relation["contacts"] == [
        {"name": "Jan de Bakker", "function": "Directeur", "email": "jan@goudenbol.example"},
    ]


@pytest.mark.asyncio
async def test_relation_without_email_address_reports_none(connect, call_tool):
    async with connect() as session:
        _, relation = await call_tool(session, "get_relation", relation_id=1004)

    assert (relation["name"], relation["email"], relation["email_invoice"]) == ("Noordzee Advies", None, None)


@pytest.mark.asyncio
async def test_unknown_relation_is_a_tool_error(connect, call_tool):
    async with connect() as session:
        is_error, text = await call_tool(session, "get_relation", relation_id=9999)

    assert is_error
    assert "404" in text
