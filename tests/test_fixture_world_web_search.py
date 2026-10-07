"""
tests/test_fixture_world_web_search.py

In Fixture-world mode (`--fixtures` and evals) the web search is the Fixture world's: seeded
results, under the real tool's name and argument shape, classified read. Nothing reaches
Tavily (the suite runs with a dummy key and no network).
"""

import json

import pytest
import pytest_asyncio
from langchain_core.messages import AIMessage

from agent.evals.harness import run_eval
from agent.evals.scenarios import load_dataset
from agent.tools import load_all_tools
from agent.tools.classification import is_read
from agent.tools.web import web_search


@pytest_asyncio.fixture
async def fixture_web_search():
    tools, _ = await load_all_tools(fixtures=True)
    [search] = [t for t in tools if t.name == web_search.name]
    return search


@pytest.mark.asyncio
async def test_fixture_world_binds_a_web_search_shaped_like_the_real_one_and_classified_read(fixture_web_search):
    assert fixture_web_search is not web_search
    assert fixture_web_search.name == "tavily_search"
    assert (fixture_web_search.tool_call_schema.model_json_schema()
            == web_search.tool_call_schema.model_json_schema())
    assert is_read(fixture_web_search)


@pytest.mark.asyncio
async def test_fixture_world_web_search_returns_the_seeded_results_for_a_query(fixture_web_search):
    result = await fixture_web_search.ainvoke({"query": "route planning software for a small logistics company"})

    assert result["query"] == "route planning software for a small logistics company"
    titles = [r["title"] for r in result["results"]]
    assert "RouteWise: route planning for small fleets" in titles
    assert all(r["url"].startswith("https://") and r["content"] for r in result["results"])


@pytest.mark.asyncio
async def test_fixture_world_web_search_honours_domain_filters(fixture_web_search):
    result = await fixture_web_search.ainvoke({"query": "route planning software",
                                               "include_domains": ["routewise.example"]})

    assert [r["url"] for r in result["results"]] == ["https://routewise.example/small-fleets"]


@pytest.mark.asyncio
async def test_fixture_world_web_search_finds_nothing_off_its_seeded_topics(fixture_web_search):
    result = await fixture_web_search.ainvoke({"query": "weather in Lisbon"})

    assert result["results"] == []


@pytest.mark.asyncio
async def test_an_eval_research_run_searches_the_fixture_world_without_approval(scripted_model, tmp_path):
    path = tmp_path / "scenarios.json"
    path.write_text(json.dumps({"format_version": 1, "dataset_version": "v", "scenarios": [{
        "id": "research", "input": "Research route planners for a small logistics company.", "approval": "reject",
        "required_tools": ["tavily_search"], "expected_facts": ["RouteWise"],
    }]}))
    script = [
        AIMessage(content="", tool_calls=[{"id": "s", "name": "tavily_search",
                                           "args": {"query": "route planning software small logistics company"}}]),
        AIMessage(content="RouteWise suits a small fleet."),
    ]

    results = await run_eval(load_dataset(path), model_name="scripted",
                             model_factory=lambda scenario: scripted_model(script))

    [run] = results.runs
    [call] = run.tool_calls
    assert (call.name, call.status) == ("tavily_search", "success")
    assert "RouteWise" in call.output
    assert run.interrupts == []  # read: no approval prompt
    assert run.trajectory.passed
