import pytest
from _cli_harness import cli_run, mail  # noqa: F401


@pytest.mark.asyncio
async def test_the_cli_flushes_traces_before_it_exits(cli_run):
    seen, start = cli_run
    await start(["Nothing to do."])

    assert seen["flushed"] == 1
