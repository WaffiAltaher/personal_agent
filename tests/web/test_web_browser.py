"""
Browser journeys on the built app (ticket web-interface/07).

Chromium (Playwright) drives ``web/dist`` served by uvicorn from the real app factory, on the
Fixture tools with a stand-in model and a temp checkpoint file (ADR-011: no live model). Build
first (``cd web && npm run build``); install the browser with ``uv run playwright install chromium``.
The journeys carry the ``browser`` marker: ``-m "not browser"`` leaves them out.

They use Playwright's async API on each test's own event loop, which closes with the test: the
sync API would keep a loop running in the main thread and break every asyncio test after it.
"""

import asyncio
import threading

import pytest
import pytest_asyncio
import uvicorn
from playwright.async_api import Page, async_playwright, expect
from web.test_web_turns import FAST_HASHER, PASSWORD, TOOLS, StandInModel, ai, free_port

import agent.graph as graph_module
from agent.graph import build_graph, get_checkpointer
from agent.memory.episodic import EpisodicMemory
from agent.web import WebConfig, create_app
from agent.web.app import WEB_DIST

SCRIPTS = {
    "Look up my notes": [ai("", ("c1", "read_notes", {"topic": "budget"})), "Your notes are about budget."],
    "Send the report": [ai("", ("c2", "send_mail", {"to": "boss@example.com"})), "The report is sent."],
    "Send it twice": [ai("", ("c3", "send_mail", {"to": "team@example.com"})), "Sent to the team."],
}

pytestmark = [pytest.mark.browser, pytest.mark.asyncio]


@pytest.fixture(scope="module")
def app_url(tmp_path_factory):
    """The built app served on a free local port from its own thread and event loop."""
    if not (WEB_DIST / "index.html").exists():
        pytest.skip("web/dist is not built; run `cd web && npm install && npm run build`")
    tmp = tmp_path_factory.mktemp("browser")
    port = free_port()
    started, stop = threading.Event(), threading.Event()
    memory = EpisodicMemory(str(tmp / "memory.db"))
    original = graph_module.get_episodic_memory
    graph_module.get_episodic_memory = lambda: memory

    async def serve():
        db = str(tmp / "hitl.db")
        async with get_checkpointer(db) as checkpointer:
            model = StandInModel(messages=iter([]), scripts=SCRIPTS)
            app = create_app(
                graph=build_graph(checkpointer, TOOLS, model), tools=TOOLS, model=model, checkpoint_path=db,
                web=WebConfig(password_hash=FAST_HASHER.hash(PASSWORD), port=port), langfuse_connected=False,
            )
            server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
            task = asyncio.create_task(server.serve())
            while not server.started:
                await asyncio.sleep(0.01)
            started.set()
            while not stop.is_set():
                await asyncio.sleep(0.05)
            server.should_exit = True
            await task

    thread = threading.Thread(target=lambda: asyncio.run(serve()), daemon=True)
    thread.start()
    assert started.wait(15)
    yield f"http://127.0.0.1:{port}"
    stop.set()
    thread.join(10)
    graph_module.get_episodic_memory = original


@pytest_asyncio.fixture
async def page():
    """A fresh Chromium page, on this test's event loop."""
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        try:
            yield await (await browser.new_context()).new_page()
        finally:
            await browser.close()


async def log_in(page: Page, url: str):
    await page.goto(url)
    await page.locator("input[type=password]").fill(PASSWORD)
    await page.get_by_role("button", name="Log in").click()
    await expect(page.get_by_role("button", name="New Conversation")).to_be_visible()


async def ask(page: Page, question: str):
    await page.get_by_label("Question").fill(question)
    await page.get_by_role("button", name="Send", exact=True).click()


async def test_log_in_and_out(page: Page, app_url):
    await page.goto(app_url)
    await page.locator("input[type=password]").fill("wrong password")
    await page.get_by_role("button", name="Log in").click()
    await expect(page.get_by_role("button", name="New Conversation")).to_have_count(0)
    await log_in(page, app_url)
    await page.get_by_role("button", name="Log out").click()
    await expect(page.get_by_role("button", name="Log in")).to_be_visible()


async def test_a_question_shows_its_tool_step_then_the_answer(page: Page, app_url):
    await log_in(page, app_url)
    await ask(page, "Look up my notes")
    await expect(page.locator("details.step", has_text="read_notes")).to_be_visible()
    await expect(page.locator(".answer")).to_have_text("Your notes are about budget.")
    await expect(page.locator("details.step.done")).to_have_count(1)


async def test_approving_a_write_action_runs_it(page: Page, app_url):
    await log_in(page, app_url)
    await ask(page, "Send the report")
    card = page.locator('aside[aria-label="Approval"]')
    await expect(card).to_contain_text("send_mail")
    await card.get_by_role("button", name="Approve").click()
    await expect(page.locator(".answer")).to_have_text("The report is sent.")
    await expect(card).to_have_count(0)


async def test_answering_in_one_tab_updates_and_disables_the_other(page: Page, app_url):
    await log_in(page, app_url)
    await ask(page, "Send it twice")
    await expect(page.locator('aside[aria-label="Approval"]')).to_be_visible()
    second = await page.context.new_page()
    await second.goto(app_url)
    await second.get_by_role("button", name="Send it twice").first.click()
    card_two = second.locator('aside[aria-label="Approval"]')
    await expect(card_two).to_be_visible()

    await page.locator('aside[aria-label="Approval"]').get_by_role("button", name="Approve").click()

    await expect(card_two).to_have_count(0)  # the other tab's card is gone, so it cannot be answered twice
    await expect(second.locator(".answer")).to_have_text("Sent to the team.")
