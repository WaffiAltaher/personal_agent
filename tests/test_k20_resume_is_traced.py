import pytest
from _cli_harness import cli_run, mail  # noqa: F401


@pytest.mark.asyncio
async def test_the_approved_tool_call_lands_in_the_trace(cli_run):
    seen, start = cli_run
    await start([mail("ann", "c1"), "Mail sent."])

    assert seen["ran"] == ["ann"]
    assert seen["handler"].tools_started == ["send_mail"]   # the resume ran with the tracing callbacks
