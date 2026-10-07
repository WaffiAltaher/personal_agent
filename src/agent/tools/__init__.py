# src/agent/tools/__init__.py
from agent.tools.classification import read_tool, write_action
from agent.tools.filesystem import list_directory, read_file
from agent.tools.gmail import create_draft_email, get_gmail_message, search_gmail
from agent.tools.google_calendar import get_calendar_event, list_calendar_events
from agent.tools.memory import retrieve_episodic_memory, retrieve_memory
from agent.tools.web import web_search
from agent.tools.ms365_mcp import load_ms365_tools

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


async def load_all_tools():
    ms365_tools = await load_ms365_tools()
    return [
        *LOCAL_TOOLS,
        *ms365_tools,
    ]