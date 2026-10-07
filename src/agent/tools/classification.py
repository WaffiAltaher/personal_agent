# src/agent/tools/classification.py
"""
Write-action classification, failing closed.

Every tool bound to the graph is classified as read or Write action when tools
are loaded. The class is stored in the tool's metadata. The graph treats a tool
as read only if it carries the read class; anything else (classified as write,
unclassified, or a tool name that isn't bound at all) is a Write action: it
pauses for approval and is never retried automatically.

- Local tools declare their class explicitly with `read_tool` / `write_action`
  (see LOCAL_TOOLS in agent/tools/__init__.py).
- MCP tools are classified by `classify_mcp_tools`, once per server, at load time.
"""

from collections.abc import Iterable

from langchain_core.tools import BaseTool

ACTION_CLASS_KEY = "action_class"
READ = "read"
WRITE = "write"


def _set_class(tool: BaseTool, action_class: str) -> BaseTool:
    tool.metadata = {**(tool.metadata or {}), ACTION_CLASS_KEY: action_class}
    return tool


def read_tool(tool: BaseTool) -> BaseTool:
    """Declare a tool read-only: it runs without approval and may be retried."""
    return _set_class(tool, READ)


def write_action(tool: BaseTool) -> BaseTool:
    """Declare a tool a Write action: it needs approval and is never retried."""
    return _set_class(tool, WRITE)


def is_read(tool: BaseTool | None) -> bool:
    """True only for a tool explicitly classified as read. Fails closed."""
    return tool is not None and (tool.metadata or {}).get(ACTION_CLASS_KEY) == READ


def classify_mcp_tools(
    tools: Iterable[BaseTool],
    *,
    read_allowlist: Iterable[str] = (),
    trust_read_only_hint: bool = False,
) -> list[BaseTool]:
    """
    Classify one MCP server's tools. Call it once per server in the MCP loader.

    A tool is read if its name (as bound, i.e. with any server prefix) is on
    `read_allowlist`, or if `trust_read_only_hint` is set for this server and the
    tool carries the MCP `readOnlyHint: true` annotation (langchain-mcp-adapters
    copies annotations into the tool's metadata). Every other tool is a Write action.
    """
    allowlist = set(read_allowlist)
    classified = []
    for tool in tools:
        hinted_read = trust_read_only_hint and (tool.metadata or {}).get("readOnlyHint") is True
        classified.append(read_tool(tool) if tool.name in allowlist or hinted_read else write_action(tool))
    return classified
