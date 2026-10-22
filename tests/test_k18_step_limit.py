import pytest
from _cli_harness import cli_run  # noqa: F401
from langchain_core.messages import AIMessage


@pytest.mark.asyncio
async def test_a_model_that_never_stops_is_cut_off_at_the_step_limit(cli_run, monkeypatch, capsys):
    from agent.config import settings

    monkeypatch.setattr(settings, "max_iterations", 10)
    seen, start = cli_run
    calls = {"n": 0}

    def forever(messages):
        calls["n"] += 1
        if calls["n"] > 50:
            raise AssertionError("no step limit: the model was called more than 50 times")
        return AIMessage(content="", tool_calls=[{"id": f"c{calls['n']}", "name": "lookup", "args": {"query": "x"}}])

    await start([forever] * 100)
    assert calls["n"] == 10
    out = capsys.readouterr().out
    assert "step limit" in out.lower()
