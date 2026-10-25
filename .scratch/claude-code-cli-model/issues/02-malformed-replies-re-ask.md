# 02: Malformed replies are corrected once, then stop

**What to build:** When Claude's reply breaks the reply contract, the owner's run doesn't end on a single slip: the wrapper re-asks once, telling Claude what was wrong. When the second reply is also malformed, the run stops with a clear message instead of turning a broken turn into a made-up answer.

**Blocked by:** 01

**Status:** resolved

- [x] Invalid replies: not JSON, neither spec shape, an unknown tool name, args that don't validate against that tool's schema, and a reply where Claude tried to use a tool itself (more than one CLI turn)
- [x] An invalid reply triggers exactly one re-ask that carries the validation error
- [x] A valid second reply is used as normal
- [x] A second invalid reply stops the run with the validation error (if ticket 03 has landed, it uses 03's stop path; otherwise it raises a clear error that 03 will turn into a clean stop)
- [x] The re-ask's call is visible in the usage the next model call reports (ticket 04 counts it)
- [x] The whole test suite passes

Traps:
- Claude Code reports more than one turn when the model tried a tool of its own. That's the silent failure ADR-016 describes, so treat it as invalid even if the final text parses.

Spec: `../spec.md` (What comes back).
