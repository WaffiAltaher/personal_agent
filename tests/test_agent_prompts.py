"""Released system prompt versions and the default."""

from agent.config import settings
from agent.prompts import PROMPT_REGISTRY, get_prompt


def test_default_prompt_version_is_v4():
    assert settings.prompt_version == "v4"


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
    assert "v4" in PROMPT_REGISTRY
    assert len(PROMPT_REGISTRY) == 4
