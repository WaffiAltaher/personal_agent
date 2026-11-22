# tests/informer_server/test_stdio.py
"""The server runs on its own as a subprocess over stdio, configured only by INFORMER_* env vars."""

import json
import sys

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


@pytest.mark.asyncio
async def test_server_runs_standalone_over_stdio(fake_informer, tmp_path):
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "informer_mcp"],
        env={
            "INFORMER_API_KEY": fake_informer.api_key,
            "INFORMER_SECURITY_CODE": fake_informer.security_code,
            "INFORMER_BASE_URL": fake_informer.base_url,
        },
        cwd=tmp_path,  # no stray .env
    )

    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        init = await session.initialize()
        result = await session.call_tool("list_relations", {"search": "logistiek"})

    assert init.serverInfo.name == "informer"
    assert not result.isError
    assert [r["name"] for r in json.loads(result.content[0].text)["relations"]] == ["Van Dijk Logistiek B.V."]


@pytest.mark.asyncio
@pytest.mark.parametrize("configured", [True, False])
async def test_the_entry_point_offers_uploads_only_with_the_email_settings(fake_informer, tmp_path, configured):
    """Listing tools doesn't start the MS365 server, so nothing here reaches npx."""
    email = {
        "INFORMER_INCOMING_ADDRESS": "adm-91x2@scan.informer.example",
        "INFORMER_INVOICE_MAILBOX": "inkoop-scan@bedrijf.example",
        "INFORMER_MS365_PACKAGE": "@softeria/ms-365-mcp-server@0.159.1",
        "INFORMER_MS365_CLIENT_ID": "client-id",
        "INFORMER_MS365_TENANT_ID": "tenant-id",
    }
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "informer_mcp"],
        env={
            "INFORMER_API_KEY": fake_informer.api_key,
            "INFORMER_SECURITY_CODE": fake_informer.security_code,
            "INFORMER_BASE_URL": fake_informer.base_url,
            # Empty rather than unset, so the repo's .env (which the server reads wherever it starts) can't set them.
            **(email if configured else dict.fromkeys(email, "")),
        },
        cwd=tmp_path,
    )

    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        names = {tool.name for tool in (await session.list_tools()).tools}

    assert ("upload_purchase_invoice" in names) is configured
