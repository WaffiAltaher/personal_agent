# src/fixture_world/clock.py
"""The Fixture world's notion of "today".

Seed files are written for one fixed week (the week of SEED_TODAY). So that "this week"
means the seeded week whenever the Fixture world runs, seeded dates are moved by whole
weeks onto the week of `today()`, which keeps every weekday and time of day intact.

`today()` is the real date unless FIXTURE_WORLD_TODAY (an ISO date) pins it, which is how
tests and evals get a repeatable world.
"""

import os
from datetime import date, timedelta

SEED_TODAY = date(2026, 10, 7)  # a Wednesday; seed files are written relative to this week
TODAY_ENV = "FIXTURE_WORLD_TODAY"


def today() -> date:
    pinned = os.environ.get(TODAY_ENV)
    return date.fromisoformat(pinned) if pinned else date.today()


def pin_today() -> date:
    """Pin the Fixture world's "today" for this process and the stand-ins it starts, and return it:
    FIXTURE_WORLD_TODAY if set, else SEED_TODAY. A run against the Fixture world calls this
    before loading tools and tells the model the same date, so there is one "today"."""
    os.environ.setdefault(TODAY_ENV, SEED_TODAY.isoformat())
    return today()


def seed_shift(on: date | None = None) -> timedelta:
    """How far to move seeded dates so the seeded week lands on the week of `on` (default today)."""
    return _monday(on or today()) - _monday(SEED_TODAY)


def _monday(day: date) -> date:
    return day - timedelta(days=day.weekday())
