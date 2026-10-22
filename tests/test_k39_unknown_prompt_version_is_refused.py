import pytest

from agent.prompts import get_prompt


def test_an_unknown_prompt_version_is_refused():
    # A typo in PROMPT_VERSION must stop the agent, not run it on some other prompt
    # while every trace is labelled with the typo.
    with pytest.raises(ValueError, match="v9"):
        get_prompt("v9")
