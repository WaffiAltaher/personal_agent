# 05: Approval card and Stop

**What to build:** A pending Approval becomes an actionable card listing every proposed Write action and gated Outbound read, with Approve and Reject. A decision carries the id of the interrupt it answers, and is refused if that id is no longer the pending one. Every tab on the thread sees the card resolve. Sending a Follow-up while the card waits rejects it through the driver, as in the CLI. A Stop button cancels the running turn and closes its open tool calls (`close_interrupted_turn`), as Ctrl-C does.

**Blocked by:** 04

**Status:** resolved

- [x] Approve runs the Write actions and continues the turn; Reject injects the rejection and the agent acknowledges
- [x] A turn with several interrupts shows a card for each in turn
- [x] A decision with a stale interrupt id is refused; answering in one tab disables the card in the other
- [x] A Follow-up sent while an Approval waits rejects it and is answered as the next turn
- [x] Stop cancels a running turn; the thread ends on answered messages and accepts the next question
- [x] The run log entry is written after an Approval-parked, approved, rejected and stopped turn
- [x] pytest on the Fixture world covers each path

Spec: `../spec.md` (Approval, Conversations: Stop).

## Comments
