# src/agent/tools/ms365_mcp.py
"""The MS365 MCP server: the real one (@softeria/ms-365-mcp-server) or its Fixture world stand-in.

Both are loaded under the same name ("ms365"), with the same hidden tools and the same
classification, so the agent sees the same tools against either.

The model sees exactly EXPOSED_TOOLS: the read tools that `--read-only --preset outlook`
exposes, plus two Write actions that save Drafts. Nothing can send mail, and every other
write (delete, move, update, calendar changes, rules, folders, permissions) is unreachable.
The set is enforced twice: by the server's `--enabled-tools` (which also keeps the Graph
scopes it asks for to these tools: no Mail.Send) and by the loader, by name, whatever
annotations the server sets.
"""

import os
import sys

from agent.config import Settings, settings as default_settings
from agent.tools.mcp_loader import McpServer

NAME = "ms365"
PACKAGE = "@softeria/ms-365-mcp-server@0.159.1"  # exact pin; review the release diff before bumping (ADR-005)

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

# Login and account management stay out of the model's reach.
HIDDEN_TOOLS = frozenset({
    "login",
    "logout",
    "remove-account",
    "select-account",
    "verify-login",
    "list-accounts",
})


# Which tools the model sees and how they are classified, identical for the real server and the
# stand-in. Reads are classified by name, not by readOnlyHint, so no annotation can turn a
# Draft tool into an unapproved read.
_TOOL_POLICY = dict(
    hidden_tools=HIDDEN_TOOLS,
    exposed_tools=EXPOSED_TOOLS,
    read_allowlist=READ_TOOLS,
)


def ms365_server(settings: Settings = default_settings) -> McpServer:
    """The real server, through npx, against the ITtopia tenant."""
    if not (settings.ms365_mcp_client_id and settings.ms365_mcp_tenant_id):
        return McpServer(
            name=NAME,
            connection=None,
            unavailable_reason="MS365_MCP_CLIENT_ID and MS365_MCP_TENANT_ID are not set",
        )
    # The token cache stays in the macOS keychain (ADR-005): MS365_MCP_USE_KEYTAR is never set here.
    env = {
        # ENABLED_TOOLS in the environment would override --enabled-tools.
        **{key: value for key, value in os.environ.items() if key != "ENABLED_TOOLS"},
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
        },
        **_TOOL_POLICY,
    )


def enabled_tools_pattern() -> str:
    """The server's --enabled-tools regex: exactly EXPOSED_TOOLS (it is matched case-insensitively, unanchored)."""
    return "^(?:" + "|".join(sorted(EXPOSED_TOOLS)) + ")$"  # names are [a-z-] only: nothing to escape


def ms365_fixture_server() -> McpServer:
    """The Fixture world's stand-in (fixture_world.ms365), over stdio like the real one."""
    return McpServer(
        name=NAME,
        connection={
            "command": sys.executable,
            "args": ["-m", "fixture_world.ms365"],
            "transport": "stdio",
            # Passes FIXTURE_WORLD_TODAY through when set (the stdio client's default env drops it).
            "env": {**os.environ},
        },
        **_TOOL_POLICY,
    )
