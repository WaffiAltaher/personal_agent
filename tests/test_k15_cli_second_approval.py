import pytest
from _cli_harness import cli_run, mail  # noqa: F401


@pytest.mark.asyncio
async def test_the_cli_asks_again_for_a_second_approval(cli_run, capsys):
    seen, start = cli_run
    await start([mail("ann", "c1"), mail("bob", "c2"), "Both mails sent."], lines=["approve", "approve"])

    assert seen["ran"] == ["ann", "bob"]
    assert "Both mails sent." in capsys.readouterr().out
