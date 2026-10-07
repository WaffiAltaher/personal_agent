# tests/informer_server/test_credentials.py
import pytest

from fixture_world.informer_api import Failure


@pytest.mark.asyncio
async def test_rejected_credentials_name_the_settings_to_check(fake_informer, connect, call_tool):
    fake_informer.failure = Failure.UNAUTHORIZED

    async with connect() as session:
        is_error, text = await call_tool(session, "list_relations", search="logistiek")

    assert is_error
    assert "401" in text
    assert "INFORMER_API_KEY" in text and "INFORMER_SECURITY_CODE" in text


@pytest.mark.asyncio
@pytest.mark.parametrize("wrong", ["api_key", "security_code"])
async def test_wrong_credential_header_is_rejected(informer_settings, connect, call_tool, wrong):
    settings = informer_settings.model_copy(update={wrong: "not-the-right-one"})

    async with connect(settings) as session:
        is_error, text = await call_tool(session, "get_relation", relation_id=1001)

    assert is_error
    assert "INFORMER_API_KEY" in text
