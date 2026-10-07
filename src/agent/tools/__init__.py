# src/agent/tools/__init__.py
from agent.tools.filesystem import list_directory, read_file
from agent.tools.gmail import create_draft_email, get_gmail_message, search_gmail
from agent.tools.google_calendar import get_calendar_event, list_calendar_events
from agent.tools.memory import retrieve_episodic_memory, retrieve_memory
from agent.tools.web import web_search
from agent.tools.ms365_mcp import load_ms365_tools

LOCAL_TOOLS = [
    read_file,
    list_directory,
    web_search,
    list_calendar_events,
    get_calendar_event,
    search_gmail,
    get_gmail_message,
    create_draft_email,
    retrieve_memory,
    retrieve_episodic_memory,
]


async def load_all_tools():
    ms365_tools = await load_ms365_tools()
    return [
        *LOCAL_TOOLS,
        *ms365_tools,
    ]