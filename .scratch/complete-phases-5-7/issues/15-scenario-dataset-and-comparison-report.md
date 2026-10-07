# 15: Full scenario dataset + model-comparison report

**What to build:**
- A versioned dataset of 10–20 scenarios over the Fixture world, covering:
  - inbox triage
  - the overdue-invoice capstone
  - finance questions
  - research
  - failure recovery
  - rejection
- A repeats option.
- A report generator that compares two models across quality, trajectory, cost and latency, with variation across repeats.

The real Gemini vs Claude run is ticket 17.

**Blocked by:** 12, 14

**Status:** ready-for-agent

- [ ] 10–20 scenarios, each runnable against the Fixture world
- [ ] The repeats option produces per-scenario variation in the results
- [ ] The comparison report is generated from two results files
- [ ] Tested end to end with scripted models
