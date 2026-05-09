---
description: 在当前 turn 中改写下一次 echo tool call。
context: inline
hooks:
  PreToolUse:
    matcher: echo
    effect:
      updated_input:
        value: rewritten
---
改写下一次 echo tool call。
