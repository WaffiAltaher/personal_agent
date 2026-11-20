"""Browser journeys (marked ``browser``) are skipped when no Playwright browser is installed."""

import asyncio
import os

import pytest

INSTALL = "uv run playwright install chromium"


def _chromium_installed() -> bool:
    async def installed() -> bool:
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            return os.path.exists(p.chromium.executable_path)
    try:
        return asyncio.run(installed())
    except Exception:
        return False


def pytest_collection_modifyitems(config, items):
    journeys = [item for item in items if item.get_closest_marker("browser")]
    if journeys and not _chromium_installed():
        skip = pytest.mark.skip(reason=f"no Playwright browser installed; run `{INSTALL}`")
        for item in journeys:
            item.add_marker(skip)
