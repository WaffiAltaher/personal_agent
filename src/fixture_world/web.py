"""The Fixture world's web: seeded search results, so research scenarios are repeatable and free.

`search` answers a query with the seeded pages (data/web/search_results.json) that have a
keyword in the query, in Tavily's response shape, so the agent's Fixture-world web search tool
(agent.tools.web.fixture_web_search) can stand in for the real one. A query off the seeded
topics finds nothing.
"""

import json
from importlib.resources import files
from urllib.parse import urlparse


def _pages() -> list[dict]:
    return json.loads((files("fixture_world") / "data" / "web" / "search_results.json").read_text())["pages"]


def _domain_matches(url: str, domains: list[str]) -> bool:
    host = urlparse(url).hostname or ""
    return any(host == d or host.endswith(f".{d}") for d in domains)


def search(
    query: str,
    *,
    max_results: int = 5,
    include_domains: list[str] | None = None,
    exclude_domains: list[str] | None = None,
) -> dict:
    """The seeded pages matching `query`, most keyword hits first, as Tavily returns them."""
    text = query.lower()
    hits = []
    for page in _pages():
        if include_domains and not _domain_matches(page["url"], include_domains):
            continue
        if exclude_domains and _domain_matches(page["url"], exclude_domains):
            continue
        matched = sum(keyword in text for keyword in page["keywords"])
        if matched:
            hits.append((matched, page))
    hits.sort(key=lambda hit: -hit[0])  # stable: equal hits keep the seeded order
    best = hits[0][0] if hits else 1
    return {
        "query": query,
        "follow_up_questions": None,
        "answer": None,
        "images": [],
        "results": [
            {"url": page["url"], "title": page["title"], "content": page["content"],
             "score": round(matched / best, 2), "raw_content": None}
            for matched, page in hits[:max_results]
        ],
        "response_time": 0.0,
    }
