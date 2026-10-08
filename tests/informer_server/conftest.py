# tests/informer_server/conftest.py
"""Seam B harness: a real MCP client session against the Informer MCP server,
with only Informer's HTTP API faked (by the Fixture world's fake Informer API)."""

import json
from contextlib import asynccontextmanager

import pytest
from mcp import ClientSession
from mcp.shared.memory import create_connected_server_and_client_session

from fixture_world.informer_api import FakeInformerApi
from informer_mcp.config import InformerSettings
from informer_mcp.server import create_server


@pytest.fixture
def fake_informer():
    """A running fake Informer API v2 serving the seeded Fixture world."""
    with FakeInformerApi() as fake:
        yield fake


@pytest.fixture
def informer_settings(fake_informer, tmp_path) -> InformerSettings:
    """Server settings pointing at the fake, with the credentials it accepts, and a rate-limit
    budget of this test's own."""
    return InformerSettings(
        _env_file=None,
        api_key=fake_informer.api_key,
        security_code=fake_informer.security_code,
        base_url=fake_informer.base_url,
        rate_limit_dir=tmp_path / "rate-limits",
    )


@pytest.fixture
def connect(informer_settings):
    """`async with connect() as session:` opens an initialised MCP client session,
    in-process, to a server built from `informer_settings` (or the settings given).
    Keyword options (e.g. `rate_limiter=`) go to `create_server`."""

    @asynccontextmanager
    async def _connect(settings: InformerSettings | None = None, **server_options):
        server = create_server(settings or informer_settings, **server_options)
        async with create_connected_server_and_client_session(server) as session:
            yield session

    return _connect


@pytest.fixture
def call_tool():
    """`await call_tool(session, name, **args)` -> (is_error, payload).
    The payload is the parsed JSON on success and the error text on failure."""

    async def _call(session: ClientSession, name: str, **arguments):
        result = await session.call_tool(name, arguments)
        text = result.content[0].text
        if result.isError:
            return True, text
        return False, json.loads(text)

    return _call
