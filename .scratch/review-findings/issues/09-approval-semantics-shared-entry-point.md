# 09: Approval semantics and the shared entry point

**Type:** task

**Model:** Composer 2.5

**Blocked by:** 05

**Status:** ready-for-agent

**Closes:** B1, B2, B5, B6 (k10, k15; ADR-010 amendment)

**What to build:** An Approval covers only the Write actions in a step. On reject, the reads in that step still run, and each Write action gets a rejection tool message with **error** status saying the owner rejected it. The tools stage runs only tool calls that don't have an answer yet, so a rejected Write action can never execute. Every caller that starts or resumes a conversation (CLI, eval harness, future frontends) goes through one shared entry point, which: validates a resume decision (no decision is refused, not crashed on); refuses to resume a conversation that has no pending Approval (instead of silently starting an empty run); and, when a new message arrives on a conversation with a pending Approval, answers the pending Write actions as rejected ("the owner moved on without approving") before processing the new message.

- [ ] Killing tests `k10_reject_answers_every_call` and `k15_cli_second_approval` added and passing
- [ ] Test: reject on a step with one read and one Write action runs the read (its real result is in the history) and the Write action never executes
- [ ] Test: every rejection message has error status
- [ ] Test: a new message on a pending Approval produces rejections for each pending Write action, then a valid model turn; the history has no unanswered tool call
- [ ] Test: resume with no decision is refused with a clear error; resume of a conversation with no pending Approval is refused
- [ ] The CLI and the eval harness both use the shared entry point; nothing else calls the graph directly to resume

## Notes for the implementer

Trap: the standard tool node runs every tool call on the last model message. If you route to it after adding rejections, it will run the rejected Write actions. Make it skip calls that already have an answer, and prove it with the "never executes" test (assert the Write action's function was not called).

Spec: `../spec.md`. Decisions: `../findings.md` ("Decisions taken").
