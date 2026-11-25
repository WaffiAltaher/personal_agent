# src/agent/tools/classification.py
"""
Write-action classification, failing closed.

Every tool bound to the graph is classified as read or Write action when tools
are loaded. The class is stored in the tool's metadata. The graph treats a tool
as read only if it carries the read class; anything else (classified as write,
unclassified, or a tool name that isn't bound at all) is a Write action: it
pauses for approval and is never retried automatically.

A read that sends text the agent wrote to a service outside the owner's own accounts
(a web search) is an Outbound read (ADR-017). It is still a read (it changes nothing and
is retried), but it pauses for approval once the conversation holds a result from the
owner's data, so a prompt injection can't carry that data out in a query.

- Local tools declare their class explicitly with `read_tool` / `write_action` /
  `outbound_read` (see LOCAL_TOOLS in agent/tools/__init__.py).
- MCP tools are classified by `classify_mcp_tools`, once per server, at load time.
"""

from collections.abc import Callable, Iterable

from langchain_core.tools import BaseTool

ACTION_CLASS_KEY = "action_class"
READ = "read"
WRITE = "write"
OUTBOUND_READ = "outbound_read"


def _set_class(tool: BaseTool, action_class: str) -> BaseTool:
    tool.metadata = {**(tool.metadata or {}), ACTION_CLASS_KEY: action_class}
    return tool


def read_tool(tool: BaseTool) -> BaseTool:
    """Declare a tool read-only: it runs without approval and may be retried."""
    return _set_class(tool, READ)


def write_action(tool: BaseTool) -> BaseTool:
    """Declare a tool a Write action: it needs approval and is never retried."""
    return _set_class(tool, WRITE)


def outbound_read(tool: BaseTool) -> BaseTool:
    """Declare a tool an Outbound read: a read whose arguments leave the owner's accounts.

    Any new read that sends model-written text to an outside service (a search engine, a URL
    fetch) must use this, never `read_tool(...)`, or it could leak the owner's data unseen.
    """
    return _set_class(tool, OUTBOUND_READ)


def action_class(tool: BaseTool | None) -> str:
    """The tool's class; anything not explicitly classified is a Write action. Fails closed."""
    declared = (tool.metadata or {}).get(ACTION_CLASS_KEY) if tool is not None else None
    return declared if declared in (READ, OUTBOUND_READ) else WRITE


PRE_APPROVAL_CHECK_KEY = "pre_approval_check"


def with_pre_approval_check(tool: BaseTool, check: Callable[[dict], str | None]) -> BaseTool:
    """Give a Write action a check of its arguments, run before the owner is asked.

    `check` takes the call's arguments and returns an error to send back to the model, or None.
    It must be pure: the review node runs it again when the graph resumes. A call it refuses is
    never run, so it needs no Approval; it never makes a call skip one.
    """
    tool.metadata = {**(tool.metadata or {}), PRE_APPROVAL_CHECK_KEY: check}
    return tool


def pre_approval_check(tool: BaseTool | None) -> Callable[[dict], str | None] | None:
    """The tool's pre-approval check, if it has one."""
    return (tool.metadata or {}).get(PRE_APPROVAL_CHECK_KEY) if tool is not None else None


def classify_as(tool: BaseTool, action: str) -> BaseTool:
    """Give `tool` the class `action` (used for a stand-in that replaces a classified tool)."""
    return _set_class(tool, action)


def is_read(tool: BaseTool | None) -> bool:
    """True only for a tool explicitly classified as read or Outbound read. Fails closed."""
    return action_class(tool) in (READ, OUTBOUND_READ)


def is_outbound_read(tool: BaseTool | None) -> bool:
    """True only for a tool explicitly classified as an Outbound read."""
    return action_class(tool) == OUTBOUND_READ


def classify_mcp_tools(
    tools: Iterable[BaseTool],
    *,
    read_allowlist: Iterable[str] = (),
) -> list[BaseTool]:
    """
    Classify one MCP server's tools. Call it once per server in the MCP loader.

    A tool is read if its name (as bound, i.e. with any server prefix) is on
    `read_allowlist`. Every other tool is a Write action, whatever annotations
    (e.g. `readOnlyHint`) the server sets about it.
    """
    allowlist = set(read_allowlist)
    classified = []
    for tool in tools:
        classified.append(read_tool(tool) if tool.name in allowlist else write_action(tool))
    return classified
