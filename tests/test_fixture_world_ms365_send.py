"""
tests/test_fixture_world_ms365_send.py

The Fixture world's MS365 stand-in serves `send-shared-mailbox-mail` as the pinned
`@softeria/ms-365-mcp-server@0.159.1` does (Graph `POST /users/{user-id}/sendMail`), and
records every send in a file so a test (or an eval) can read back what was sent. Seam: the
stand-in's MCP tool, called directly as the Informer server's e-mail transport will call it
(the agent never binds it), and `sent_messages()` to read the record.
"""

import base64
import json
import re

import pytest
from mcp.types import CallToolResult

from agent.tools import load_all_tools
from agent.tools.ms365_mcp import ENABLED_TOOLS, EXPOSED_TOOLS, LOGIN, TRANSIENT_ERRORS
from fixture_world.ms365 import (DRAFTS_ENV, FAILURE_ENV, SEND_FAILURE_ENV, SENT_ENV, create_server, recorded_drafts,
                                 sent_messages)

INVOICE_MAILBOX = "facturen@mailbox.example"
INFORMER_ADDRESS = "boekhouding-7f3k@inkomend.example"
PDF_BYTES = b"%PDF-1.4\n\x00\xff binary \x80 bytes\n%%EOF"


@pytest.fixture
def sent_file(tmp_path, monkeypatch):
    """A fresh Fixture world: nothing sent yet."""
    path = tmp_path / "sent.jsonl"
    monkeypatch.setenv(SENT_ENV, str(path))
    return path


def _message(**overrides) -> dict:
    message = {
        "subject": "Purchase invoice: factuur-2026-031.pdf",
        "body": {"contentType": "text", "content": "Sent by ITtopia's personal agent."},
        "toRecipients": [{"emailAddress": {"address": INFORMER_ADDRESS}}],
        "attachments": [{
            "@odata.type": "#microsoft.graph.fileAttachment",
            "name": "factuur-2026-031.pdf",
            "contentType": "application/pdf",
            "contentBytes": base64.b64encode(PDF_BYTES).decode(),
        }],
    }
    return {**message, **overrides}


async def _send(message: dict | None = None, *, sender: str = INVOICE_MAILBOX, **extra) -> CallToolResult:
    """The tool call the Informer server's transport makes: the arguments of the real tool."""
    arguments = {"userId": sender, "body": {"Message": message or _message(), "SaveToSentItems": True}, **extra}
    return await create_server().call_tool("send-shared-mailbox-mail", arguments)


def _text(result: CallToolResult) -> str:
    return "".join(block.text for block in result.content)


@pytest.mark.asyncio
async def test_a_send_is_recorded_with_sender_recipients_subject_body_and_attachment(sent_file):
    result = await _send(_message(
        ccRecipients=[{"emailAddress": {"address": "cc@elsewhere.example"}}],
        bccRecipients=[{"emailAddress": {"address": "bcc@elsewhere.example"}}],
    ))

    assert not result.isError
    assert json.loads(_text(result)) == {"message": "OK!"}  # what the real server answers to Graph's 202
    assert sent_messages(sent_file) == [{
        "sender": INVOICE_MAILBOX,
        "to": [INFORMER_ADDRESS],
        "cc": ["cc@elsewhere.example"],
        "bcc": ["bcc@elsewhere.example"],
        "subject": "Purchase invoice: factuur-2026-031.pdf",
        "body": "Sent by ITtopia's personal agent.",
        "attachments": [{"name": "factuur-2026-031.pdf", "content_type": "application/pdf", "content": PDF_BYTES}],
        "save_to_sent_items": True,
    }]


@pytest.mark.asyncio
async def test_the_tool_is_listed_with_the_argument_shape_and_annotations_of_the_pinned_server():
    """Expected values are from the pinned server's own tool listing (0.159.1, --org-mode), not the stand-in."""
    [tool] = [t for t in await create_server().list_tools() if t.name == "send-shared-mailbox-mail"]

    assert sorted(tool.inputSchema["required"]) == ["body", "userId"]
    assert sorted(tool.inputSchema["properties"]) == ["body", "confirm", "excludeResponse", "includeHeaders", "userId"]
    assert tool.annotations.readOnlyHint is False
    assert tool.annotations.destructiveHint is True
    assert tool.annotations.openWorldHint is True


@pytest.mark.asyncio
async def test_a_body_content_type_the_pinned_server_does_not_accept_sends_nothing(sent_file):
    """The pinned server's schema allows lowercase `text` or `html` only and rejects `Text`."""
    result = await _send(_message(body={"contentType": "Text", "content": "Sent by ITtopia's personal agent."}))

    assert result.isError
    assert "contentType" in _text(result)
    assert sent_messages(sent_file) == []


@pytest.mark.asyncio
async def test_a_body_without_a_message_is_a_graph_bad_request_and_sends_nothing(sent_file):
    result = await create_server().call_tool(
        "send-shared-mailbox-mail", {"userId": INVOICE_MAILBOX, "body": {"SaveToSentItems": True}})

    assert result.isError
    assert "400" in _text(result)
    assert sent_messages(sent_file) == []


@pytest.mark.asyncio
async def test_logged_out_fails_the_send_as_the_real_server_reports_it_and_records_nothing(sent_file, monkeypatch):
    monkeypatch.setenv(FAILURE_ENV, "logged-out")

    result = await _send()

    assert result.isError
    assert any(re.search(pattern, _text(result)) for pattern in LOGIN.error_patterns)
    assert sent_messages(sent_file) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["transient", "throttled"])
async def test_a_transient_failure_fails_the_send_as_the_real_server_reports_it_and_records_nothing(
        sent_file, monkeypatch, mode):
    monkeypatch.setenv(FAILURE_ENV, mode)

    result = await _send()

    assert result.isError
    assert any(re.search(pattern, _text(result)) for pattern in TRANSIENT_ERRORS)
    assert sent_messages(sent_file) == []


@pytest.mark.asyncio
async def test_the_send_failure_switch_fails_the_send_only_not_reads_or_drafts(sent_file, tmp_path, monkeypatch):
    monkeypatch.setenv(SEND_FAILURE_ENV, "transient")
    monkeypatch.setenv(DRAFTS_ENV, str(tmp_path / "drafts.jsonl"))
    server = create_server()

    sent = await _send()
    read = await server.call_tool("list-mail-messages", {"top": 1})
    draft = await server.call_tool("create-draft-email", {"body": {"subject": "Reminder"}})

    assert sent.isError
    assert any(re.search(pattern, _text(sent)) for pattern in TRANSIENT_ERRORS)
    assert sent_messages(sent_file) == []
    assert not read.isError
    assert not draft.isError
    assert [d["subject"] for d in recorded_drafts(tmp_path / "drafts.jsonl")] == ["Reminder"]


@pytest.mark.asyncio
async def test_the_agent_never_enables_or_binds_a_send_tool():
    """Only the Informer server's own copy of the MS365 server may send (ADR-019)."""
    sending = {"send-shared-mailbox-mail", "send-mail"}

    assert not sending & EXPOSED_TOOLS
    assert not sending & ENABLED_TOOLS
    tools, _ = await load_all_tools(fixtures=True)  # the stand-in serves both tools; neither is bound
    assert not [t.name for t in tools if t.name.removeprefix("ms365_") in sending]
