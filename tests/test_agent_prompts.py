"""Released system prompt versions and the default."""

import ast
import inspect

import agent.prompts
from agent.config import settings
from agent.prompts import PROMPT_REGISTRY, get_prompt


def test_default_prompt_version_is_v7():
    assert settings.prompt_version == "v7"


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
    assert "v7" in PROMPT_REGISTRY
    assert len(PROMPT_REGISTRY) == 7


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


def test_v7_adds_the_purchase_invoice_rules_and_otherwise_matches_v6():
    v6, v7 = get_prompt("v6"), get_prompt("v7")
    assert v7.startswith(v6)
    added = " ".join(v7[len(v6):].split())
    # The invoice date comes from the PDF, or from the owner.
    assert "read_pdf_text" in added
    assert "ask the owner" in added
    # The Processed check runs first and its target path is passed unchanged.
    assert "ms365_check_invoice_archive" in added
    assert "unchanged" in added
    # One upload asked for while the other is missing.
    assert "informer_check_purchase_invoice" in added
    assert '"Process instead?"' in added
    # A Process is both uploads in one turn; a failure offers the remaining step.
    assert "informer_upload_purchase_invoice" in added
    assert "ms365_upload_to_onedrive" in added
    assert "one turn" in added
    assert "remaining step" in added
    # The status line, and the listing that matches names only.
    assert "Uploaded to Informer: yes (<date>)/no · Uploaded to OneDrive: yes (<path>)/no" in added
    assert "ms365_list_invoice_archive" in added
    assert "names only" in added
    for term in ("Upload to Informer", "Upload to OneDrive", "Process", "Processed", "Invoice archive"):
        assert term in added
