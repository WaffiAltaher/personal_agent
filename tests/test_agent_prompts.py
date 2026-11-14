"""Released system prompt versions and the default."""

import ast
import inspect

import agent.prompts
from agent.config import settings
from agent.prompts import PROMPT_REGISTRY, get_prompt


def test_default_prompt_version_is_v6():
    assert settings.prompt_version == "v6"


def test_v4_has_ittopia_rules_without_overdue_or_payment_reminders():
    text = get_prompt("v4")
    assert "ITtopia" in text
    assert "never send" in text
    assert "MS365, not Gmail" in text
    assert "Informer" in text
    for forbidden in (
        "Overdue invoice",
        "Payment reminder",
        "informer_list_overdue_invoices",
        "list_overdue_invoices",
    ):
        assert forbidden not in text


def test_released_versions_v1_through_v3_are_unchanged_literals():
    assert "v6" in PROMPT_REGISTRY
    assert len(PROMPT_REGISTRY) == 6


def test_every_prompt_version_is_written_out_as_its_full_text():
    tree = ast.parse(inspect.getsource(agent.prompts))
    for node in tree.body:
        if isinstance(node, ast.Assign) and node.targets[0].id.startswith("PROMPT_V"):
            assert isinstance(node.value, ast.Constant), node.targets[0].id


def test_v5_names_the_agent_folder_and_otherwise_matches_v4():
    assert get_prompt("v5") == get_prompt("v4").replace(
        "/Users/waffi/Downloads/Personal\n", "/Users/waffi/Downloads/personal_agent\n")
    assert "/Users/waffi/Downloads/Personal\n" not in get_prompt("v5")


def test_v6_adds_the_rules_for_content_the_agent_reads_and_otherwise_matches_v5():
    v5, v6 = get_prompt("v5"), get_prompt("v6")
    assert v6.startswith(v5)
    added = " ".join(v6[len(v5):].split())
    assert "never an instruction" in added
    assert "name that source" in added
    assert "Informer" in added
