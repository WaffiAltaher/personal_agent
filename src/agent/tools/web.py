"""
Web tools for the personal data agent.

Currently: Tavily web search, and its Fixture-world stand-in.
Tavily is purpose-built for LLM agents — it returns clean, structured results
rather than raw HTML, which means less token waste and less parsing logic here.
"""

from langchain_core.tools import StructuredTool
from langchain_tavily import TavilySearch
from langchain_tavily.tavily_search import TavilySearchInput

from agent.config import settings
from fixture_world import web as fixture_web


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


def _search_fixture_world(
    query: str,
    include_domains: list[str] | None = None,
    exclude_domains: list[str] | None = None,
    **unused,  # search_depth, time_range, topic, ...: the seeded web ignores them
) -> dict:
    return fixture_web.search(query, max_results=web_search.max_results,
                              include_domains=include_domains, exclude_domains=exclude_domains)


# The Fixture world's stand-in for web_search (`--fixtures` and evals): seeded results
# (fixture_world/web.py), under the same tool name and argument shape, so the model sees the
# same tool either way and research scenarios are repeatable and free.
fixture_web_search = StructuredTool.from_function(
    func=_search_fixture_world,
    name=web_search.name,
    description=web_search.description,
    args_schema=TavilySearchInput,
)
