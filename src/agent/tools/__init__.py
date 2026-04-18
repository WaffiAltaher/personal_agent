# src/agent/tools/__init__.py
from agent.tools.filesystem import list_directory, read_file
from agent.tools.gmail import get_gmail_message, search_gmail
from agent.tools.google_calendar import get_calendar_event, list_calendar_events
from agent.tools.web import web_search

ALL_TOOLS = [
    read_file,
    list_directory,
    web_search,
    list_calendar_events,
    get_calendar_event,
    search_gmail,
    get_gmail_message,
]
