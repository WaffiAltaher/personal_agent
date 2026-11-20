# src/informer_mcp/email_handover.py
"""Purchase invoice hand-over by e-mail (ADR-019): one message per invoice, from the Invoice
mailbox to the Informer incoming address, sent through an MS365 server started per upload."""

import base64
import os
import re
import tempfile
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import TextContent

from informer_mcp.config import InformerSettings

SEND_TOOL = "send-shared-mailbox-mail"
BODY = "Sent by ITtopia's personal agent."
# The MS365 server's arguments after the package. `--org-mode` is needed: without it the pinned
# server doesn't register work-scoped tools such as this one.
SERVER_ARGS = ["--org-mode", "--enabled-tools", f"^(?:{SEND_TOOL})$"]

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


def ms365_server_parameters(settings: InformerSettings) -> StdioServerParameters:
    """The real MS365 server, through npx, with only the send tool enabled."""
    # This process's environment is already the agent's allowlist (system basics and INFORMER_*);
    # the server gets the basics and its own settings, never Informer's API key. ENABLED_TOOLS
    # would override --enabled-tools, and MS365_MCP_USE_KEYTAR would move the token cache.
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(("INFORMER_", "MS365_MCP_")) and key != "ENABLED_TOOLS"}
    for name, value in (("MS365_MCP_CLIENT_ID", settings.ms365_client_id),
                        ("MS365_MCP_TENANT_ID", settings.ms365_tenant_id),
                        ("MS365_MCP_EXPECTED_USERNAME", settings.ms365_expected_username)):
        if value:
            env[name] = value
    return StdioServerParameters(
        command="npx",
        args=["-y", settings.ms365_package or "", *SERVER_ARGS],
        env=env,
        # Outside the repo: the server reads a `.env` from its working directory on its own.
        cwd=tempfile.gettempdir(),
    )


def stdio_connection(params: StdioServerParameters) -> Ms365Connection:
    """Starts the server in `params` for each session, over stdio."""

    @asynccontextmanager
    async def session():
        async with stdio_client(params) as (read, write), ClientSession(read, write) as client:
            await client.initialize()
            yield client

    return session


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
