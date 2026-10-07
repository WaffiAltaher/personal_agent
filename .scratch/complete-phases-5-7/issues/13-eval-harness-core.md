# 13: Eval harness core + trajectory metrics

**What to build:** The learner runs one command to evaluate the agent on scenarios over the Fixture world, with a chosen model. Each scenario declares:
- the input
- the approval policy (auto-approve or auto-reject)
- any failure to inject
- the required tools and ordering constraints
- the forbidden tools
- the expected answer facts

The harness scores trajectory metrics: tool-selection precision and recall, whether ordering constraints were met, forbidden-tool violations, and recovery after an injected failure. It writes results JSON and a markdown report.

**Blocked by:** 06, 11

**Status:** ready-for-agent

- [ ] Versioned scenario format and loader
- [ ] Runner injects the model and applies the approval policy and failure injection
- [ ] Trajectory metrics computed per scenario and aggregated
- [ ] Tested with a scripted fake model on 2 scenarios (one pass, one deliberate trajectory failure)
