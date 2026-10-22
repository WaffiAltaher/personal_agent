import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from fixture_world.informer_api import FakeInformerApi
from informer_mcp.config import InformerSettings
from informer_mcp.server import create_server


@pytest.mark.asyncio
async def test_a_per_minute_429_is_reported_as_transient(tmp_path):
    with FakeInformerApi() as fake:
        fake.spend(minute=60)  # another client of the same API key used this whole minute
        settings = InformerSettings(_env_file=None, api_key=fake.api_key, security_code=fake.security_code,
                                    base_url=fake.base_url, rate_limit_dir=tmp_path)

        async with create_connected_server_and_client_session(create_server(settings)) as session:
            result = await session.call_tool("get_sales_invoice", {"invoice_id": 5001})

    text = result.content[0].text
    assert result.isError
    assert "HTTP 429" in text
    assert "Transient Informer failure" in text  # the host retries only errors with this prefix
    assert int(fake.quota_headers()["X-DailyLimit-Remaining"]) > 0  # not the daily quota
