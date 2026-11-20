# 03: List and open Conversations

**What to build:** After login the app shows every real Conversation in the checkpoint file, CLI-started ones included, newest activity first, each titled by its first question (cut to about 80 characters) with its date. Opening one shows its questions, answers and tool steps (collapsed detail), and any pending Approval as a read-only card for now. Answers are rendered as Markdown with raw HTML disabled. Nothing can be renamed or deleted.

**Blocked by:** 02

**Status:** resolved

- [x] The list shows threads from the real checkpoint file, ordered by latest checkpoint
- [x] A thread started with the CLI appears with its first question as title
- [x] Listing stays fast with several hundred threads (test with a seeded checkpoint file)
- [x] Opening a thread shows every turn, with tool calls as collapsible steps (arguments and results as escaped text)
- [x] An answer containing `<script>` or other HTML is shown as text, never executed (test it)
- [x] A thread parked at an Approval shows the pending card with its actions
- [x] pytest covers the list and transcript endpoints on a Fixture-world checkpoint file

Spec: `../spec.md` (Conversations, Rendering).

## Comments
