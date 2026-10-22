# tests/informer_server/test_prompts.py
"""MCP prompts on the Informer server (Payment reminder removed in ADR-012)."""

import pytest


@pytest.mark.asyncio
async def test_server_exposes_no_prompts(connect):
    async with connect() as session:
        listed = await session.list_prompts()
    assert listed.prompts == []
