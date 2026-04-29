---
description: Rewrite the next echo tool call in the current turn.
context: inline
hooks:
  PreToolUse:
    matcher: echo
    effect:
      updated_input:
        value: rewritten
---
Rewrite the next echo tool call.
