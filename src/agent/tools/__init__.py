# src/agent/tools/__init__.py
from langchain_core.tools import BaseTool

from agent.tools.classification import read_tool, write_action
from agent.tools.filesystem import list_directory, read_file
from agent.tools.gmail import create_draft_email, get_gmail_message, search_gmail
from agent.tools.google_calendar import get_calendar_event, list_calendar_events
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


# In Fixture-world mode the web search is the Fixture world's (seeded results, same name and
# arguments); the other local tools are unchanged.
FIXTURE_LOCAL_TOOLS = [read_tool(fixture_web_search) if t is web_search else t for t in LOCAL_TOOLS]


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