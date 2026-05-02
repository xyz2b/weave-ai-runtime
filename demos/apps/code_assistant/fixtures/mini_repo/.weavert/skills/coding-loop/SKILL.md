---
description: Enforce the main coding loop discipline in the current turn.
context: inline
user-invocable: false
---
Follow this order in the current turn:

1. Enter the planning phase first for non-trivial work by asking the `coding-planner` agent for a short ordered plan.
2. Keep the shared task list current throughout the turn.
3. Inspect the workspace with `glob`, `grep`, or `read` before editing.
4. Make the smallest useful edit with `edit` or `write`.
5. Run verification through `bash`, using session actions or jobs only when the command is longer-lived.
6. Run the explicit verification phase and then the explicit review phase before the final summary.
7. Make sure verifier output starts with `verification: pass` or `verification: fail`.
8. Make sure reviewer output starts with `review: pass` or `review: fail`.
9. Finish with a concise summary naming changed files, verification, review, and any remaining workflow gaps.
