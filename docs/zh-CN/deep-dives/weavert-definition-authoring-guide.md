# WeaveRT Tool、Agent 与 Skill 编写指南

> 文档说明：这是 definition authoring contracts 的 deep-dive 参考。普通路径请先从 `docs/zh-CN/concepts/tools-agents-skills.md` 开始，再读相应 guides。

## 对应主文档

- Tools / agents / skills concepts -> `docs/zh-CN/concepts/tools-agents-skills.md`
- First real project path -> `docs/zh-CN/guides/build-your-first-project.md`
- Add a tool -> `docs/zh-CN/guides/add-a-tool.md`
- Add an agent -> `docs/zh-CN/guides/add-an-agent.md`
- Add a skill -> `docs/zh-CN/guides/add-a-skill.md`

这篇文档重点回答：

- `DefinitionSourcePaths` discovery 与 precedence 实际如何工作
- 哪些字段属于稳定 runtime contract，哪些只是被解析
- file-backed tools 如何验证
- skill hooks 与 agent hooks 的边界是什么
- 内置 OpenAI route 会带来哪些 transport 约束

## 1. 核心姿态

定义类型仍应明确区分：

- tool
- agent
- skill

## 2. Discovery 与 precedence

常见 roots：

- `~/.weavert`
- `<project>/.weavert`

同名优先级：

- 同名 bundled definition 会压过 user 与 project definitions
- 同名 user definition 会压过 project definitions

因此 project-local 文件不是静默 built-in override 机制。

## 3. Tool 编写契约

### 3.1 支持的 file-backed 形态

支持：

- `TOOL_DEFINITION`
- `TOOL`
- `build_tool_definition()`

默认不支持：

- `.weavert/tools/*.json`
- `.weavert/tools/*.yaml`
- `.weavert/tools/*.yml`
- 用 mapping 替代 `ToolDefinition`
- 没有 `execute` 的 file-backed tool

### 3.2 稳定 `ToolDefinition` 字段

关键 traits 包括：

- `read_only`
- `concurrency_safe`
- `destructive`
- `interrupt_behavior`

原则是 traits 必须诚实描述真实行为。

### 3.3 面向非内置 tools 的公开执行边界

普通 tool 可以读到：

- session、turn 与 agent metadata
- 工作目录与当前 messages
- tool / agent / skill catalogs
- permission context

但不应依赖：

- internal runtime services
- raw tool pool internals
- mutable private-context internals

### 3.4 内置 OpenAI route 的 schema 指南

- 顶层 schema 应声明 `type: object`
- object properties 导出时应 `additionalProperties: false`
- optional fields 会被规范化为 required + nullable
- schema-valued `additionalProperties` 不受支持，会触发 `tool_schema_error`

## 4. Agent 编写契约

### 4.1 文件结构

- frontmatter
- prompt body

### 4.2 稳定 runtime-facing 字段

最值得依赖的是角色、描述、工具池、skills、权限与 memory / isolation posture。

### 4.3 稳定编写建议

- 工具列表应明显小于 “everything”
- 把角色定义得足够清楚
- 执行细节交给 tools，而不是塞进 prompt prose
- 有意识地设置 memory 与 isolation，而不是盲目继承默认值

### 4.4 被解析但尚未成熟的字段

- `hooks`
- `initialPrompt`
- `criticalSystemReminder_EXPERIMENTAL`
- `mcpServers`

其中 agent-owned hooks 不是普通推荐路径，默认 assembly 会拒绝它们。

## 5. Skill 编写契约

### 5.1 文件结构

- frontmatter
- Markdown body

### 5.2 稳定 runtime-facing 字段

重点是 `context`、allowed tools、hooks 与 paths。

### 5.3 `inline` 与 `fork`

`inline` 适合：

- 把 prompt 或 workflow guidance 注入当前 turn
- 在不创建 child run 的前提下收窄策略

`fork` 适合：

- 创建 child-agent run
- 获得独立执行边界
- 留下单独 child-run record

### 5.4 Skill hooks 是成熟的 definition-level hook 路径

- skill hooks 有真实 runtime 语义
- 在 inline 与 fork 路径中都能工作
- inline hooks 跟随当前 session/turn 生命周期释放
- fork hooks 可跟随 child execution 一起传播

### 5.5 Shell expansion 边界

- 只适用于本地 file-backed skills
- bundled skills 不应依赖它
- 所需 shell tool 必须真的可用
- 不可用时应 fail closed，而不是静默跳过

### 5.6 Path activation 是 runtime 语义

要区分：

- skill 是否可见
- 用户是否可调用
- 模型是否可调用

## 6. 验证清单

常见检查方式：

- `weavert.resolve_invocations(...)`
- `weavert.visible_invocations(session)`
- `weavert.invocation_diagnostics(session)`

Discovery 还不够；还要确认最终解析后的定义仍保留可运行的 `execute`。

## 7. 相关文档

- `docs/zh-CN/deep-dives/weavert-integration-guide.md`
- `docs/zh-CN/deep-dives/weavert-control-plane-extension-guide.md`
- `docs/zh-CN/deep-dives/current-system-architecture.md`
- `docs/zh-CN/deep-dives/weavert-openai-responses-adapter.md`
