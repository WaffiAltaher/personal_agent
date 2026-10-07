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
