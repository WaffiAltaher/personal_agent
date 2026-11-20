# src/informer_mcp/email_handover.py
"""Purchase invoice hand-over by e-mail (ADR-019): one message per invoice, from the Invoice
mailbox to the Informer incoming address, sent through an MS365 server started per upload."""

import base64
import re
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

from mcp import ClientSession
from mcp.types import TextContent

from informer_mcp.config import InformerSettings

SEND_TOOL = "send-shared-mailbox-mail"
BODY = "Sent by ITtopia's personal agent."

# The MS365 server's wording for a missing or expired login, as in agent.tools.ms365_mcp.LOGIN
# (not imported: this server runs without the agent's settings).
LOGIN_ERRORS = (
    r"No valid token found",
    r"No access token available",
    r"token may have expired",
    r"Microsoft Graph API error: 401\b",
)

# Opens an initialised session to a freshly started MS365 server, and stops it on exit.
Ms365Connection = Callable[[], AbstractAsyncContextManager[ClientSession]]


def login_command(package: str) -> str:
    return f"npx -y {package} --login (with MS365_MCP_CLIENT_ID and MS365_MCP_TENANT_ID set)"


class EmailHandover:
    def __init__(
        self, ms365: Ms365Connection, *, invoice_mailbox: str, incoming_address: str, login_command: str,
    ):
        self.ms365 = ms365
        self.invoice_mailbox = invoice_mailbox
        self.incoming_address = incoming_address
        self.login_command = login_command

    async def hand_over(self, file_name: str, content: bytes) -> None:
        message = {
            "subject": f"Purchase invoice: {file_name}",
            "body": {"contentType": "text", "content": BODY},
            "toRecipients": [{"emailAddress": {"address": self.incoming_address}}],
            "attachments": [{
                "@odata.type": "#microsoft.graph.fileAttachment",
                "name": file_name,
                "contentType": "application/pdf",
                "contentBytes": base64.b64encode(content).decode(),
            }],
        }
        arguments = {"userId": self.invoice_mailbox, "body": {"Message": message, "SaveToSentItems": True}}
        async with self.ms365() as session:
            result = await session.call_tool(SEND_TOOL, arguments)
        if not result.isError:  # Graph's 202
            return
        text = "\n".join(b.text for b in result.content if isinstance(b, TextContent))
        if any(re.search(pattern, text) for pattern in LOGIN_ERRORS):
            text += (f"\nNot logged in to Microsoft 365. Log in with `{self.login_command}`, "
                     "then upload the invoice again.")
        raise RuntimeError(text)


def email_handover(settings: InformerSettings, ms365: Ms365Connection) -> EmailHandover | None:
    """The e-mail hand-over through `ms365`, or None when a setting it needs is missing."""
    required = (settings.incoming_address, settings.invoice_mailbox, settings.ms365_package,
                settings.ms365_client_id, settings.ms365_tenant_id)
    if not all(required):
        return None
    return EmailHandover(
        ms365,
        invoice_mailbox=settings.invoice_mailbox,
        incoming_address=settings.incoming_address,
        login_command=login_command(settings.ms365_package),
    )
