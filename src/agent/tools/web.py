"""
Web tools for the personal data agent.

Currently: Tavily web search.
Tavily is purpose-built for LLM agents — it returns clean, structured results
rather than raw HTML, which means less token waste and less parsing logic here.
"""

from langchain_tavily import TavilySearch

from agent.config import settings


# TavilySearch is a LangChain-wrapped tool (from the dedicated `langchain-tavily`
# package, which replaces the deprecated `TavilySearchResults` in
# langchain-community) that:
# - Calls the Tavily API with the query
# - Returns the top-k results as a structured dict of {query, results, ...}
# - Is already decorated as a @tool, so it integrates with ToolNode directly
# - Already defines its own args_schema, so we do NOT define a custom input
#   schema here — it would be ignored anyway.
#
# We set max_results=5 as a reasonable default — enough context without
# flooding the LLM's context window with irrelevant content.
#
# The api_key is passed explicitly (loaded from .env via pydantic-settings)
# rather than relying on TAVILY_API_KEY being set in os.environ.
# This keeps our credential loading in one place (config.py).
web_search = TavilySearch(
    max_results=5,
    tavily_api_key=settings.tavily_api_key,
)
