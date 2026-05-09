# 工具、智能体与技能

WeaveRT 有意把这三类扩展类型分开。
它们解决的是不同问题；如果你希望 runtime 保持可组合性，就应让它们继续彼此独立。

## 适合谁？

- 已经理解落地页定位、现在需要核心运行时词汇的使用者。

## 前置条件

- 先读 `../introduction/what-is-weavert.md`
- 如果你想把术语和可运行路径对应起来，快速浏览 `../getting-started/quickstart.md`

## 一览表

| 表面 | 负责什么 | 什么时候用 | 文件型路径 |
| --- | --- | --- | --- |
| Tool | 执行与结构化 I/O | 当你需要带 schema、traits 和 permissions 的可复用能力 | `.weavert/tools/*.py` |
| Agent | 角色与 prompt posture | 当你需要一个具名 worker，如 reviewer、planner 或 support agent | `.weavert/agents/*.md` |
| Skill | 可复用工作流步骤 | 当你需要一个具名过程，如 summarize、verify 或 review | `.weavert/skills/**/SKILL.md` |

## 发现表面

Runtime 通过 `DefinitionSourcePaths` 发现本地定义。
默认 ordinary workflow 路径包含：

- `~/.weavert`
- `<project>/.weavert`

默认文件型发现规则为：

- tools：`tools/*.py`
- agents：`agents/*.md`
- skills：`skills/**/SKILL.md`

## Source precedence 很重要

本地文件并不是一个“神奇覆盖系统”。
当前实际优先级是：

- bundled
- user
- project

这意味着：如果一个 project-local 文件与某个 bundled built-in 同名，不应把它当成默认覆盖策略。
更好的做法是：

- 给 project-local 定义起一个新名字
- 如果你确实需要替换 bundled surface，在 Python assembly 代码里使用 `BuiltinPackConfig`

## Tools

Tools 做“工作”本身。
最适合这些场景：

- 文件检查或修改
- API 或服务调用
- 结构化项目分析
- 被多个 agents 或 skills 共享的可复用能力

重要的编写规则：

- 文件型 tools 是 Python 模块，不是 JSON 或 YAML
- 模块应导出一个具体的 `ToolDefinition`
- 明确的对象 schema 优于开放式 payload
- `read_only`、`concurrency_safe`、`destructive` 等 traits 应诚实反映真实行为

## Agents

Agents 负责角色行为和 prompt 身份。
最适合这些场景：

- 一个可复用的 reviewer 或 planner
- 一个具有更窄工具池的 worker
- 更大工作流里的具名 delegated role

好的 agent 设计习惯：

- tool 列表要明显比 “everything” 更窄
- prompt 聚焦在角色、输出和决策姿态
- 让工具承担执行细节，而不是把细节都写进 prompt prose

还要注意：agent-owned hooks 不是普通推荐路径。
当你需要生命周期注入时，优先选择：

- skill hooks
- runtime/session/host 的 hook 注册

## Skills

Skills 用于打包可复用工作流步骤。
适合这些场景：

- 可重复的 summarize / verify / review 步骤
- 带参数的小型可复用流程
- 应以内联或子 agent 方式运行的具名操作

一个很好的首要设计问题是：skill 应该如何运行？

- `inline`
  - 当你想停留在当前 turn 上下文内
- `fork`
  - 当你想让它以 child agent 的方式运行，获得更清晰的 delegated boundary

## 不是某个 agent 私有特性的运行时原语

有些表面看起来像 workflow-specific 功能，但应该被视为 framework-level primitives，而不是某个私有 agent 的小技巧。
两个典型例子是：

- `task_*`
- `job_*`

如果你的设计依赖共享任务列表或作业监控，应把它们看成可被多个 agents 或 hosts 观察的运行时能力表面，而不是单一 prompt 约定。

## 什么时候 package 是更好的抽象

如果你的改动已经不只是添加一个本地 tool、agent 或 skill，而是需要：

- manifest-backed capability group
- dependency ordering
- capability registry lookups
- lifecycle participation

那你大概率已经从本地定义编写跨到了 package composition。
这个边界请继续看 `packages-and-scenario-packs.md`。

## 常见错误

- 把执行逻辑写进 agent prompt，而不是 tool
- 用 skill 处理一个其实简单 tool 就足够的问题
- 期待 project-local 名称悄悄覆盖 bundled built-ins
- 试图只靠更多 `.weavert/` 文件夹来表达 package 所有权

## 下一步

- 通过 `../guides/add-a-tool.md`、`../guides/add-an-agent.md` 或 `../guides/add-a-skill.md` 开始编写
- 如果你的改动已经超出单个本地定义，进入 `packages-and-scenario-packs.md`

## 另见

- `../guides/add-a-tool.md`
- `../guides/add-an-agent.md`
- `../guides/add-a-skill.md`
- `packages-and-scenario-packs.md`
- `../deep-dives/weavert-definition-authoring-guide.md`
