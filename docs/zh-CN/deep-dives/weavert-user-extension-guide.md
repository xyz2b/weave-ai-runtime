# WeaveRT 用户扩展指南

> 文档说明：这是用户扩展层的 deep-dive 参考。普通路径请先读 `docs/zh-CN/concepts/tools-agents-skills.md` 与对应 guides。

## 对应主文档

- Tools / agents / skills boundary -> `docs/zh-CN/concepts/tools-agents-skills.md`
- First real project path -> `docs/zh-CN/guides/build-your-first-project.md`
- Add a tool -> `docs/zh-CN/guides/add-a-tool.md`
- Add an agent -> `docs/zh-CN/guides/add-an-agent.md`
- Add a skill -> `docs/zh-CN/guides/add-a-skill.md`
- Control plane -> `docs/zh-CN/guides/extend-the-control-plane.md`

## 1. 先分开扩展层

### 1.1 Definition authoring

- `tool`
- `agent`
- `skill`

### 1.2 Package 与 control-plane extension

- `RuntimePackageManifest`
- `PackageContribution`
- `HostRuntime`
- stable public hooks
- context contributors
- model routes
- `tool_refresh_callback`

### 1.3 基础设施与持久化

- `TranscriptStore`
- `ChildRunStore`
- `MemoryConfig`
- `MemoryProvider`
- `teammate_orchestration`

## 2. 扩展决策图

一个实用规则是：

- 只改一个局部能力，优先写本地 tool / agent / skill
- 一旦涉及 manifest、依赖排序、capability lookup 或 context contributors，就跨入 package 层
- 一旦涉及 transcript、child runs、memory backend 或 host-owned control plane，就进入基础设施层

## 3. Package-owned 与 definition-owned 的区别

继续使用本地 definitions 的情况：

- 某个能力只属于单个项目
- 不需要 manifest admission 或 dependency ordering
- 改动仍可被理解为一个 tool、agent 或 skill

转向 package 的情况：

- 一个功能拥有多个 runtime surfaces
- 需要 manifest-backed activation
- 需要 capability lookup、context contributors 或 host facets
- 你在组合一个 scenario profile 或 shared capability family

还要记住：

- 同名 project definitions 不会覆盖 bundled built-ins
- built-in replacement 属于 `BuiltinPackConfig`，而不是靠文件名冲突实现

## 4. 基础设施与持久化边界

### 4.1 TranscriptStore

回答：

- transcript history 是否应 durable
- session truth 应存在哪里
- recovery / audit 如何读取历史 sessions

### 4.2 ChildRunStore

重点字段：

- run identity
- parent linkage
- status
- final-state metadata

### 4.3 MemoryConfig

主要负责：

- retrieval posture
- extraction posture
- session-memory refresh thresholds
- consolidation cadence

### 4.4 MemoryProvider 与 runtime memory service

- `MemoryProvider`
- runtime-owned memory service replacement

需要注意：当前没有直接的 `RuntimeConfig.memory_provider` 槽位。

### 4.5 `teammate_orchestration`

只有当你真的需要团队协作与委派平面时，才进入这一层。

## 5. 用户当前不应过度依赖的东西

- agent-owned hooks
- agent frontmatter `initialPrompt`
- agent frontmatter `criticalSystemReminder_EXPERIMENTAL`
- agent frontmatter `mcpServers`
- 用户自定义 tools 上听起来像 privileged execution 的 flags
- `ToolDefinition.output_schema`
- `ToolDefinition.search_hint`

更适合稳定依赖的字段：

- tool：`input_schema`、`validate_input`、`check_permissions`、`execute`
- agent：`tools`、`disallowedTools`、`skills`、`permissionMode`、`memory`、`isolation`、`modelRoute`
- skill：`context`、`allowed-tools`、`hooks`、`paths`

## 6. 用户导向验证与 examples

- `docs/zh-CN/guides/add-a-tool.md`
- `docs/zh-CN/guides/add-an-agent.md`
- `docs/zh-CN/guides/add-a-skill.md`
- `docs/zh-CN/guides/bind-a-host.md`
- `docs/zh-CN/guides/testing-and-observability.md`
- `examples/README.zh-CN.md`
- `docs/zh-CN/maintainers/demo-validation-findings.md`

## 7. 推荐实践

1. 先走 starter-first 路径
2. 先扩展本地 definitions，再考虑 packages
3. 先验证离线 seam，再进入 live route
4. 只有在需要 app-owned UX / approvals 时再绑定 host
5. 对不成熟字段保持保守依赖

## 8. 相关文档

- `docs/zh-CN/deep-dives/weavert-definition-authoring-guide.md`
- `docs/zh-CN/deep-dives/weavert-integration-guide.md`
- `docs/zh-CN/deep-dives/weavert-control-plane-extension-guide.md`
- `docs/zh-CN/deep-dives/weavert-hook-configuration-platform.md`
- `docs/zh-CN/deep-dives/weavert-scenario-runtime-pack-architecture.md`
- `docs/zh-CN/deep-dives/current-system-architecture.md`
