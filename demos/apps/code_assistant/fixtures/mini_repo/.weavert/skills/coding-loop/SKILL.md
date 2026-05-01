---
description: Enforce the main coding loop discipline in the current turn.
context: inline
user-invocable: false
---
Follow this order in the current turn:

1. Ask the `coding-planner` agent for a short plan when the task is non-trivial.
2. Keep the shared task list current.
3. Inspect the workspace with `glob`, `grep`, or `read` before editing.
4. Make the smallest useful edit with `edit` or `write`.
5. Verify with `bash`, using background jobs only when the command is long-running.
6. Run review and verification passes before the final summary.
7. Finish with a concise summary naming files changed, verification, and outcomes.
