# src/agent/tools/__init__.py
from langchain_core.tools import BaseTool

from agent.tools.classification import ACTION_CLASS_KEY, READ, read_tool, write_action
from agent.tools.filesystem import list_directory, read_file
from agent.tools.gmail import (
    create_draft_email,
    fixture_create_draft_email,
    fixture_get_gmail_message,
    fixture_search_gmail,
    get_gmail_message,
    search_gmail,
)
from agent.tools.google_calendar import (
    fixture_get_calendar_event,
    fixture_list_calendar_events,
    get_calendar_event,
    list_calendar_events,
)
from agent.tools.memory import retrieve_episodic_memory, retrieve_memory
from agent.tools.web import fixture_web_search, web_search
from agent.tools.mcp_loader import McpServer, load_mcp_tools
from agent.tools.ms365_mcp import ms365_fixture_server, ms365_server
from agent.tools.informer import informer_fixture_server, informer_server

# Every local tool declares its class explicitly: read, or Write action.
# An undeclared tool is treated as a Write action (see classification.py).
LOCAL_TOOLS = [
    read_tool(read_file),
    read_tool(list_directory),
    read_tool(web_search),
    read_tool(list_calendar_events),
    read_tool(get_calendar_event),
    read_tool(search_gmail),
    read_tool(get_gmail_message),
    write_action(create_draft_email),  # saves a draft to Gmail
    read_tool(retrieve_memory),
    read_tool(retrieve_episodic_memory),
]


# In Fixture-world mode, web search and the Google tools are seeded stand-ins (same names and
# arguments); the other local tools are unchanged.
_FIXTURE_STAND_INS_BY_NAME = {
    web_search.name: fixture_web_search,
    search_gmail.name: fixture_search_gmail,
    get_gmail_message.name: fixture_get_gmail_message,
    create_draft_email.name: fixture_create_draft_email,
    list_calendar_events.name: fixture_list_calendar_events,
    get_calendar_event.name: fixture_get_calendar_event,
}


def _fixture_local_tool(tool: BaseTool) -> BaseTool:
    stand_in = _FIXTURE_STAND_INS_BY_NAME.get(tool.name)
    if stand_in is None:
        return tool
    action = (tool.metadata or {}).get(ACTION_CLASS_KEY)
    if action == READ:
        return read_tool(stand_in)
    return write_action(stand_in)


FIXTURE_LOCAL_TOOLS = [_fixture_local_tool(t) for t in LOCAL_TOOLS]


def mcp_servers(*, fixtures: bool = False) -> list[McpServer]:
    """The MCP servers the agent loads tools from: the real ones, or the Fixture world's."""
    if fixtures:
        return [ms365_fixture_server(), informer_fixture_server()]
    return [ms365_server(), informer_server()]


async def load_all_tools(*, fixtures: bool = False) -> tuple[list[BaseTool], list[str]]:
    """Local tools plus every available MCP server's tools, and notices about unavailable servers."""
    mcp_tools, notices = await load_mcp_tools(mcp_servers(fixtures=fixtures))
    return [
        *(FIXTURE_LOCAL_TOOLS if fixtures else LOCAL_TOOLS),
        *mcp_tools,
    ], notices