# src/agent/tools/ms365_mcp.py
"""The MS365 MCP server: the real one (@softeria/ms-365-mcp-server) or its Fixture world stand-in.

Both are loaded under the same name ("ms365"), with the same exposed tools and the same
classification, so the agent sees the same tools against either.

The model sees exactly EXPOSED_TOOLS: the read tools that `--read-only --preset outlook`
exposes, plus two Write actions that save Drafts. Nothing can send mail, and every other
write (delete, move, update, calendar changes, rules, folders, permissions) is unreachable.
The set is enforced twice: by the server's `--enabled-tools` (which also keeps the Graph
scopes it requests to these tools, so it asks for no Mail.Send; the token it gets may still
carry every permission granted to the app, ADR-019) and by the loader, by name, whatever
annotations the server sets.

With ENABLED_TOOLS the server requests the delegated Mail.Read, Mail.ReadWrite (Drafts),
Calendars.Read, Contacts.Read, MailboxSettings.Read and User.Read, and, for the drive tools,
Files.ReadWrite (it collapses Files.Read into it, ADR-020). The Azure app grants each of them
(the setup wizard's Azure app stage).

The loader also binds `ms365_save_attachment`, the agent's own Write action over the server's
`download-bytes-to-file` (ADR-015), in place of that raw tool, and `ms365_list_invoice_archive`
and `ms365_check_invoice_archive` (the Processed check), the agent's own reads over the drive
tools, and `ms365_upload_to_onedrive`, its Write action over `create-upload-session`, all fixed to
the Invoice archive (ADR-020). The upload's PUT of the bytes is agent code: httpx against
OneDrive, the Fixture world's own against the stand-in.
"""

import sys
import tempfile

from agent.config import Settings, settings as default_settings
from agent.tools.mcp_environment import fixture_environment, system_environment
from agent.tools.mcp_loader import LoginCheck, McpServer
from agent.tools.ms365_attachments import DOWNLOAD_TOOL, SAVE_ATTACHMENT
from agent.tools.ms365_invoice_archive import (
    CHECK_INVOICE_ARCHIVE,
    CREATE_FOLDER_TOOL,
    LIST_DRIVES_TOOL,
    LIST_FOLDER_TOOL,
    LIST_INVOICE_ARCHIVE,
    UPLOAD_SESSION_TOOL,
    PutToSession,
    httpx_put,
    upload_to_onedrive,
)
from fixture_world.ms365 import put_upload_session

NAME = "ms365"
PACKAGE = "@softeria/ms-365-mcp-server@0.159.1"  # exact pin; review the release diff before bumping (ADR-005)

# Both servers start here, not in the repo: the real server reads a `.env` from its working
# directory on its own, and this keeps the repo's secrets out of its reach.
WORKING_DIRECTORY = tempfile.gettempdir()

# What `--read-only --preset outlook` exposes at the pinned version without --org-mode
# (Graph GET tools, POST tools the server marks read-only, and download-bytes), minus
# download-bytes-to-file: it writes a local file although the server annotates it readOnlyHint.
READ_TOOLS = frozenset({
    "download-bytes",
    "get-calendar-event",
    "get-calendar-view",
    "get-mail-message",
    "get-mail-message-mime",
    "get-mail-tips",
    "get-mailbox-settings",
    "get-outlook-contact",
    "get-specific-calendar-event",
    "get-specific-calendar-view",
    "list-calendar-event-instances",
    "list-calendar-events",
    "list-calendar-events-delta",
    "list-calendar-view-delta",
    "list-calendars",
    "list-contact-folder-child-folders",
    "list-contact-folder-contacts",
    "list-contact-folders",
    "list-focused-inbox-overrides",
    "list-mail-attachments",
    "list-mail-child-folders",
    "list-mail-folder-messages",
    "list-mail-folder-messages-delta",
    "list-mail-folders",
    "list-mail-messages",
    "list-mail-rules",
    "list-my-calendar-permissions",
    "list-outlook-categories",
    "list-outlook-contacts",
    "list-specific-calendar-events",
    "list-supported-languages",
    "list-supported-time-zones",
})

# The only Write actions: they save a Draft in Outlook for the owner to review and send.
DRAFT_TOOLS = frozenset({"create-draft-email", "create-reply-draft"})

EXPOSED_TOOLS = READ_TOOLS | DRAFT_TOOLS

# What the server enables: the exposed tools, plus download-bytes-to-file, which only the
# agent's own ms365_save_attachment calls (it is a GET: no new Graph scope), and the drive tools
# the Invoice archive wrappers call (they add Files.ReadWrite, ADR-020). Never bound. Never
# upload-file-content: it overwrites without warning and carries the bytes in the call.
DRIVE_TOOLS = frozenset({LIST_DRIVES_TOOL, LIST_FOLDER_TOOL, CREATE_FOLDER_TOOL, UPLOAD_SESSION_TOOL})
ENABLED_TOOLS = EXPOSED_TOOLS | {DOWNLOAD_TOOL} | DRIVE_TOOLS

# Login and account management (login, logout, verify-login, list-/select-/remove-account)
# are not in EXPOSED_TOOLS, so they stay out of the model's reach. The real server serves
# them whatever --enabled-tools says (in stdio mode it registers its auth tools separately
# from the filtered Graph tools), so the loader can still call verify-login at startup.

# A missing or expired login: checked at startup with verify-login, and recognised in
# tool errors by the real server's wording (a token error, or Graph answering 401).
LOGIN = LoginCheck(
    service="Microsoft 365",
    command=f"npx -y {PACKAGE} --login (with MS365_MCP_CLIENT_ID and MS365_MCP_TENANT_ID set)",
    check_tool="verify-login",
    error_patterns=(
        r"No valid token found",
        r"No access token available",
        r"token may have expired",
        r"Microsoft Graph API error: 401\b",
    ),
)

# The real server reports Graph errors as tool errors worded
# "Microsoft Graph API error: <status> <reason> - <body>"; 429 and 5xx are transient.
TRANSIENT_ERRORS = (r"Microsoft Graph API error: (429|5\d\d)\b",)


# Which tools the model sees and how they are classified, identical for the real server and the
# stand-in (only the upload's PUT differs). Reads are classified by name, not by readOnlyHint, so
# no annotation can turn a Draft tool into an unapproved read.
def _tool_policy(put: PutToSession) -> dict:
    return dict(
        exposed_tools=EXPOSED_TOOLS,
        read_allowlist=READ_TOOLS,
        login=LOGIN,
        transient_errors=TRANSIENT_ERRORS,
        wrappers=(
            SAVE_ATTACHMENT,  # bound in place of download-bytes-to-file
            LIST_INVOICE_ARCHIVE,  # a read, bound in place of list-folder-files
            CHECK_INVOICE_ARCHIVE,  # a read (the Processed check), also in place of list-folder-files
            upload_to_onedrive(put),  # a Write action, bound in place of create-upload-session
        ),
    )


def ms365_server(settings: Settings = default_settings) -> McpServer:
    """The real server, through npx, against the ITtopia tenant."""
    if not (settings.ms365_mcp_client_id and settings.ms365_mcp_tenant_id):
        return McpServer(
            name=NAME,
            connection=None,
            unavailable_reason="MS365_MCP_CLIENT_ID and MS365_MCP_TENANT_ID are not set",
        )
    # Only the system basics and this server's own settings (see mcp_environment). So the shell's
    # MS365_MCP_USE_KEYTAR and ENABLED_TOOLS never reach the server: the token cache stays in the
    # macOS keychain (ADR-005), and ENABLED_TOOLS would override --enabled-tools.
    env = {
        **system_environment(),
        "MS365_MCP_CLIENT_ID": settings.ms365_mcp_client_id,
        "MS365_MCP_TENANT_ID": settings.ms365_mcp_tenant_id,
    }
    if settings.ms365_mcp_expected_username:
        # The server fails fast when the cached account isn't this one.
        env["MS365_MCP_EXPECTED_USERNAME"] = settings.ms365_mcp_expected_username
    return McpServer(
        name=NAME,
        connection={
            "command": "npx",
            "args": [
                "-y",
                PACKAGE,
                # Replaces --preset outlook (a preset would override this flag); an anchored
                # pattern of exact names from that preset.
                "--enabled-tools",
                enabled_tools_pattern(),
            ],
            "transport": "stdio",
            "env": env,
            "cwd": WORKING_DIRECTORY,
        },
        **_tool_policy(httpx_put),
    )


def enabled_tools_pattern() -> str:
    """The server's --enabled-tools regex: exactly ENABLED_TOOLS (it is matched case-insensitively, unanchored)."""
    return "^(?:" + "|".join(sorted(ENABLED_TOOLS)) + ")$"  # names are [a-z-] only: nothing to escape


def ms365_fixture_server() -> McpServer:
    """The Fixture world's stand-in (fixture_world.ms365), over stdio like the real one."""
    return McpServer(
        name=NAME,
        connection={
            "command": sys.executable,
            "args": ["-m", "fixture_world.ms365"],
            "transport": "stdio",
            # The Fixture world's own settings (its clock, failure switches, draft log) and the system basics.
            "env": fixture_environment(),
            "cwd": WORKING_DIRECTORY,  # as the real server: outside the repo
        },
        **_tool_policy(put_upload_session),  # its PUT completes the stand-in's upload session
    )
