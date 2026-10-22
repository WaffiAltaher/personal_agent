# 07: Fixture-world stand-ins for Gmail and Google Calendar

**Type:** task

**Model:** Composer 2.5

**Blocked by:** None (can start immediately)

**Status:** resolved

**Closes:** G1 (ADR-011 amendment)

**What to build:** In Fixture-world mode (tests, evals, `--fixtures`), the Gmail and Google Calendar tools are replaced by seeded stand-ins with the **same tool names, arguments and Write-action classification** as the real ones, following the existing web-search stand-in. Seed data (a handful of personal emails and calendar events, dated relative to the Fixture-world clock) lives with the other Fixture-world seed files. Today the real Google tools are bound in Fixture-world mode, so evals can read the owner's real inbox.

- [x] In Fixture-world mode no bound tool reaches Google: test that loading tools with fixtures binds the stand-ins, and that no real Google tool is in the list
- [x] The stand-ins return seeded results for the same arguments the real tools take; the Draft-creating Gmail tool stays a Write action
- [x] Seeded dates move with the Fixture-world clock like the other seed data
- [x] Real mode still binds the real tools unchanged
- [x] Full test suite passes, with no Google credentials present

## Notes for the implementer

Follow how the web-search stand-in replaces its real tool. Don't change the real tools' names or arguments: the stand-in must be a drop-in.

Spec: `../spec.md`. Decisions: `../findings.md` ("Decisions taken").

## Comments

Seeded stand-ins in `fixture_world/google.py` (data under `data/google/`); wired via `FIXTURE_LOCAL_TOOLS` like `fixture_web_search`. `tests/test_fixture_world_google.py` covers binding, classification, seeded results, clock shift. Full suite: 238 passed (2026-10-22).
