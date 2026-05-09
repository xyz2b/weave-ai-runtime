# 添加 Skill

## 适合谁？

想要一个可复用工作流步骤的用户，例如 summarize、verify、review 或 clarify。

## 前置条件

- 一个包含 `.weavert/skills/` 的可运行项目
- 一个应被命名并复用的重复性工作流步骤

## 第一个设计选择：inline 还是 fork

在编写 skill 之前，先决定它如何运行：

- `inline`
  - 当它应停留在当前 turn 上下文里
- `fork`
  - 当它应作为 child agent 步骤运行，并拥有更清晰的 delegated boundary

## 步骤

1. 创建 `.weavert/skills/release-summary/SKILL.md`
2. 选择 `inline` 或 `fork`
3. 保持参数与预期输出简洁、显式
4. 在组合更大工作流之前，先验证你选择的执行模式

最小示例：

```md
---
description: Draft a short release summary in a child agent run.
context: fork
agent: skill-writer
---
Draft a release summary for ${ARG1}.
```

## 什么时候 Hook 属于 skill

如果某个额外行为应当随着 skill 本身一起移动，那么 skill hooks 是普通推荐路径。
它通常比 agent-owned hooks 更合适，因为真正拥有该行为的是 workflow step，而不是整个 agent 身份。

## 好的 skill 边界

一个 skill 通常应该：

- 表达一个可复用过程
- 范围明显小于整个 app shell
- 不要变成堆放各种无关 prompt 行为的地方
- 对调用方暴露干净契约

## 预期结果

Runtime 能发现这个 skill，并把它作为一个可复用、具名的 workflow step 来执行。

## 下一步

用 `python3 -B -m examples.skills.file_backed_skill_demo`、`python3 -B -m examples.skills.inline_vs_fork_skill_demo` 或 `python3 -B -m examples.skills.inline_skill_hook_demo` 验证这个 seam。

## 另见

- `../concepts/tools-agents-skills.md`
- `../../../examples/skills/workspace/.weavert/skills/release-summary/SKILL.md`
- `../deep-dives/weavert-definition-authoring-guide.md`
