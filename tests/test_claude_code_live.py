"""
tests/test_claude_code_live.py

The one check against the real Claude Code CLI, with the production flags (ADR-016). It alerts
the maintainer when a Claude Code update breaks the flags, the result shape, the reply contract,
or the isolation from the owner's own setup. Marked live: it uses the owner's subscription.
Run explicitly: pytest -m live -k claude_code
"""

import json
import shutil

import pytest
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool

from agent.chat_model import create_chat_model
from agent.config import settings

# About 1k on 2026-10-25; about 55k when the owner's CLAUDE.md, memory and skills load again.
_MAX_CONTEXT_TOKENS = 5000


@tool
def get_weather(city: str) -> str:
    """The current weather in one city."""
    return "sunny"


@pytest.mark.live
def test_real_claude_code_asks_for_both_tool_calls_in_one_turn_with_a_small_context(tmp_path):
    real = shutil.which("claude")
    if real is None:
        pytest.skip("blocked: no claude binary on PATH")
    # A pass-through that keeps each raw CLI result, so the test sees the turns and calls made.
    results = tmp_path / "results.jsonl"
    wrapper = tmp_path / "claude"
    wrapper.write_text(f'#!/bin/sh\n"{real}" "$@" | tee -a "{results}"\necho >> "{results}"\n')
    wrapper.chmod(0o755)
    model = create_chat_model("claude_code:haiku", settings=settings.model_copy(update={"claude_code_binary": str(wrapper)}))

    reply = model.bind_tools([get_weather]).invoke(
        [HumanMessage("What is the weather in Amsterdam and in Utrecht right now?")]
    )

    raw = [json.loads(line) for line in results.read_text().splitlines() if line.strip()]
    assert len(raw) == 1, raw  # no re-ask
    assert raw[0]["num_turns"] == 1, raw
    assert raw[0]["is_error"] is False, raw
    assert sorted(c["name"] for c in reply.tool_calls) == ["get_weather", "get_weather"]
    assert sorted(c["args"]["city"] for c in reply.tool_calls) == ["Amsterdam", "Utrecht"]
    usage = reply.usage_metadata
    assert usage["output_tokens"] > 0
    # input_tokens counts the cache reads and writes too: the whole context Claude was sent.
    assert 0 < usage["input_tokens"] < _MAX_CONTEXT_TOKENS, usage
    assert "haiku" in reply.response_metadata["model_name"]
