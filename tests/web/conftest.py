"""Browser journeys (test_web_browser.py) are skipped when no Playwright browser is installed."""

import os

import pytest

INSTALL = "uv run playwright install chromium"


def _chromium_installed() -> bool:
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            return os.path.exists(p.chromium.executable_path)
    except Exception:
        return False


def pytest_collection_modifyitems(config, items):
    journeys = [item for item in items if item.path.name == "test_web_browser.py"]
    # Playwright's sync API keeps an event loop running in the main thread until the session ends,
    # which breaks asyncio.run() in any test after it: run the journeys last.
    items[:] = [item for item in items if item not in journeys] + journeys
    if journeys and not _chromium_installed():
        skip = pytest.mark.skip(reason=f"no Playwright browser installed; run `{INSTALL}`")
        for item in journeys:
            item.add_marker(skip)
