# tests/informer_server/test_email_transport.py
"""The e-mail transport (ADR-019): an approved upload is one e-mail from the Invoice mailbox to the
Informer incoming address, sent through an MS365 server the Informer server starts per upload.

Seam: the Informer server over an in-memory MCP session, with the Fixture world's MS365 stand-in
as its MS365 server; what was sent is read back from the stand-in's sent log."""

import re
from datetime import date
from pathlib import Path

import pytest

from agent.tools.ms365_mcp import LOGIN
from fixture_world import informer as fixture_informer, ms365 as stand_in
from informer_mcp.email_handover import LOGIN_ERRORS, email_handover, ms365_server_parameters, stdio_connection

REPO_ROOT = Path(__file__).resolve().parents[2]

# Not the Fixture world's defaults, so a hard-coded address fails.
INVOICE_MAILBOX = "inkoop-scan@bedrijf.example"
INCOMING_ADDRESS = "adm-91x2@scan.informer.example"
PACKAGE = "@softeria/ms-365-mcp-server@0.159.1"
PDF = b"%PDF-1.4\n\x00\xff binary \x80 bytes\n%%EOF\n"


@pytest.fixture
def downloads(tmp_path) -> Path:
    folder = tmp_path / "Downloads"
    folder.mkdir()
    return folder


@pytest.fixture
def settings(informer_settings, downloads, tmp_path):
    return informer_settings.model_copy(update={
        "downloads_dir": downloads,
        "purchase_upload_log": tmp_path / "state" / "purchase-uploads.jsonl",
        "today": date(2026, 10, 7),
        "incoming_address": INCOMING_ADDRESS,
        "invoice_mailbox": INVOICE_MAILBOX,
        "ms365_package": PACKAGE,
        "ms365_client_id": "client-id",
        "ms365_tenant_id": "tenant-id",
    })


@pytest.mark.asyncio
async def test_an_upload_sends_one_email_from_the_invoice_mailbox_to_the_incoming_address_only(
    connect, settings, ms365, downloads, call_tool,
):
    pdf = downloads / "factuur-2026-031.pdf"
    pdf.write_bytes(PDF)

    async with connect(settings, handover=email_handover(settings, ms365.connect)) as session:
        is_error, payload = await call_tool(session, "upload_purchase_invoice", path=str(pdf))

    assert not is_error, payload
    assert ms365.sent() == [{
        "sender": INVOICE_MAILBOX,
        "to": [INCOMING_ADDRESS],
        "cc": [],
        "bcc": [],
        "subject": "Purchase invoice: factuur-2026-031.pdf",
        "body": "Sent by ITtopia's personal agent.",
        "attachments": [{"name": "factuur-2026-031.pdf", "content_type": "application/pdf", "content": PDF}],
        "save_to_sent_items": True,
    }]


@pytest.mark.asyncio
async def test_the_upload_says_the_invoice_was_sent_to_informer_not_uploaded_or_booked(
    connect, settings, ms365, downloads, call_tool,
):
    pdf = downloads / "factuur.pdf"
    pdf.write_bytes(PDF)

    async with connect(settings, handover=email_handover(settings, ms365.connect)) as session:
        tools = {tool.name: tool for tool in (await session.list_tools()).tools}
        _, payload = await call_tool(session, "upload_purchase_invoice", path=str(pdf))

    for text in (payload["message"], tools["upload_purchase_invoice"].description):
        words = " ".join(text.lower().split())
        assert re.search(r"\bsen[dt]\b.*\bto informer\b", words), text
        assert not re.search(r"\b(upload|uploaded|booked)\b", words), text


@pytest.mark.asyncio
async def test_reads_never_start_the_ms365_server(connect, settings, ms365, downloads, call_tool):
    pdf = downloads / "factuur.pdf"
    pdf.write_bytes(PDF)

    async with connect(settings, handover=email_handover(settings, ms365.connect)) as session:
        results = [
            await call_tool(session, "revenue", year=2026),
            await call_tool(session, "trial_balance", year=2026),
            await call_tool(session, "list_relations"),
            await call_tool(session, "check_purchase_invoice", path=str(pdf)),
        ]
        await session.read_resource("informer://administration")

    assert [is_error for is_error, _ in results] == [False] * 4
    assert ms365.starts == 0


@pytest.mark.asyncio
async def test_a_login_error_is_the_uploads_error_names_the_login_command_and_logs_nothing(
    connect, settings, ms365, downloads, call_tool, monkeypatch,
):
    monkeypatch.setenv(stand_in.FAILURE_ENV, "logged-out")
    pdf = downloads / "factuur.pdf"
    pdf.write_bytes(PDF)

    async with connect(settings, handover=email_handover(settings, ms365.connect)) as session:
        is_error, text = await call_tool(session, "upload_purchase_invoice", path=str(pdf))
        _, checked = await call_tool(session, "check_purchase_invoice", path=str(pdf))

    assert is_error
    assert stand_in.NO_TOKEN in text
    assert f"npx -y {PACKAGE} --login" in text
    assert ms365.starts == 1
    assert ms365.sent() == []
    assert "already_uploaded_on" not in checked
    assert not settings.purchase_upload_log.exists()


def test_the_transport_recognises_a_login_error_as_the_agent_does():
    assert LOGIN_ERRORS == LOGIN.error_patterns


@pytest.mark.asyncio
@pytest.mark.parametrize("switch,mode", [
    (stand_in.FAILURE_ENV, "transient"),
    (stand_in.FAILURE_ENV, "throttled"),
    (stand_in.SEND_FAILURE_ENV, "transient"),
])
async def test_a_transient_error_is_the_uploads_error_sent_at_most_once_and_logs_nothing(
    connect, settings, ms365, downloads, call_tool, monkeypatch, switch, mode,
):
    monkeypatch.setenv(switch, mode)
    pdf = downloads / "factuur.pdf"
    pdf.write_bytes(PDF)

    async with connect(settings, handover=email_handover(settings, ms365.connect)) as session:
        is_error, text = await call_tool(session, "upload_purchase_invoice", path=str(pdf))

    assert is_error
    assert re.search(r"Microsoft Graph API error: (429|503)\b", text)
    assert "--login" not in text
    assert ms365.starts == 1
    assert ms365.sent() == []
    assert not settings.purchase_upload_log.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode,cause", [
    (stand_in.Failure.DOWN, "ms365 stand-in: switched down (Failure.DOWN)"),  # exits at start, as on a username mismatch
    (stand_in.Failure.CRASH, "The MS365 server stopped"),  # dies mid-call, saying nothing
])
async def test_a_server_that_fails_to_start_or_crashes_is_the_uploads_error_with_its_cause(
    connect, settings, ms365, downloads, call_tool, monkeypatch, mode, cause,
):
    monkeypatch.setenv(stand_in.FAILURE_ENV, mode)
    pdf = downloads / "factuur.pdf"
    pdf.write_bytes(PDF)
    ms365_over_stdio = stdio_connection(fixture_informer.ms365_stand_in_parameters())

    async with connect(settings, handover=email_handover(settings, ms365_over_stdio)) as session:
        is_error, text = await call_tool(session, "upload_purchase_invoice", path=str(pdf))

    assert is_error
    assert cause in text
    assert "TaskGroup" not in text
    assert ms365.sent() == []
    assert not settings.purchase_upload_log.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", [
    "incoming_address", "invoice_mailbox", "ms365_package", "ms365_client_id", "ms365_tenant_id",
])
async def test_with_a_required_setting_missing_neither_upload_tool_is_listed(connect, settings, ms365, missing):
    incomplete = settings.model_copy(update={missing: None})

    async with connect(incomplete, handover=email_handover(incomplete, ms365.connect)) as session:
        init = await session.initialize()
        names = {tool.name for tool in (await session.list_tools()).tools}

    assert not names & {"check_purchase_invoice", "upload_purchase_invoice"}
    assert "upload" not in (init.instructions or "").lower()
    assert "revenue" in names  # the reads stay


@pytest.mark.asyncio
async def test_without_the_expected_username_the_upload_tools_are_listed(connect, settings, ms365):
    async with connect(settings, handover=email_handover(settings, ms365.connect)) as session:
        names = {tool.name for tool in (await session.list_tools()).tools}

    assert settings.ms365_expected_username is None
    assert {"check_purchase_invoice", "upload_purchase_invoice"} <= names


def test_the_real_ms365_server_is_the_pinned_package_with_only_the_send_tool_outside_the_repo(
    settings, monkeypatch,
):
    monkeypatch.setenv("INFORMER_API_KEY", "informer-key-decoy")  # the Informer process has it
    monkeypatch.setenv("ENABLED_TOOLS", ".*")  # would override --enabled-tools
    monkeypatch.setenv("MS365_MCP_USE_KEYTAR", "false")  # would move the token cache out of the keychain
    settings = settings.model_copy(update={"ms365_expected_username": "jendo@example.com"})

    params = ms365_server_parameters(settings)

    assert params.command == "npx"
    assert params.args[:2] == ["-y", PACKAGE]
    assert "--org-mode" in params.args
    # The server tests each tool name against the pattern case-insensitively, without anchoring.
    pattern = re.compile(params.args[params.args.index("--enabled-tools") + 1], re.IGNORECASE)
    assert pattern.search("send-shared-mailbox-mail")
    for other in ("send-mail", "send-shared-mailbox-mail-x", "create-draft-email", "list-mail-messages"):
        assert not pattern.search(other), other
    cwd = Path(params.cwd).resolve()
    assert cwd.is_dir() and not cwd.is_relative_to(REPO_ROOT)
    assert {key: params.env[key] for key in params.env if key.startswith("MS365_MCP_")} == {
        "MS365_MCP_CLIENT_ID": "client-id",
        "MS365_MCP_TENANT_ID": "tenant-id",
        "MS365_MCP_EXPECTED_USERNAME": "jendo@example.com",
    }
    assert not [key for key in params.env if key.startswith("INFORMER_") or key == "ENABLED_TOOLS"]
