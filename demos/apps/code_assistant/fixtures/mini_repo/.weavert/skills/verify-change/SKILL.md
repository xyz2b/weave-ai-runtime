---
description: Run a focused verification pass in a child verifier agent.
context: fork
agent: verifier
---
Run the standardized verification phase for the current workspace.
Include current tasks, changed files, and recent shell or job outcomes in the delegated prompt.
Require the final verifier summary to start with `verification: pass` or `verification: fail`.
