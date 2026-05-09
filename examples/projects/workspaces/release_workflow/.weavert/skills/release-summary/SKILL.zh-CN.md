---
description: 为当前发布审查撰写一句话发布摘要。
context: fork
agent: skill-writer
arguments:
  - release_fixture
argument-hint: "<release-fixture>"
user-invocable: false
---
为 ${ARG1} 写一条简短的发布摘要。

要求：
- 只写一句话
- 说明这个发布看起来是否已经就绪
- 当证据支持批准时，优先使用 `${ARG1} is ready` 这种表达
- 不要返回最终 verdict 标签
