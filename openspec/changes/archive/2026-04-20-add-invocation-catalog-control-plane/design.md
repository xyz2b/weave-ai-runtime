## Context

当前 runtime 在 skill execution 方向已经具备比较完整的语义：

- `SKILL.md` frontmatter 已解析到 `SkillDefinition`
- inline / fork execution 已区分
- `allowed-tools` 已进入 non-escalation policy narrowing
- hook ownership、permission 与 isolation ceiling 已接入 shared control plane

但在 capability exposure 方向仍有明显缺口：

- `paths` activation 仍停留在 registry-only 过滤，没有真正接入 session / turn runtime
- `user-invocable`、`disable-model-invocation`、`argument-hint`、`when_to_use` 等字段尚未形成 runtime semantics
- `SessionCommand` 只是 inbound event queue，不是统一 invocation catalog
- host、模型与 `main-router` 仍主要基于原始 registry 暴露能力，而不是基于 session-scoped resolution 后的可见集合

因此本 change 不重做 skill execution backend，而是补一层独立的 invocation catalog control plane。

## Goals / Non-Goals

**Goals:**

- 将“什么能力存在、何时可见、谁可调用、为何不可用”从 execution backend 中分离出来。
- 让 skill 成为 invocation source 的一种，而不是唯一 invocation 形态。
- 让 `paths`、`user-invocable`、`disable-model-invocation` 等字段进入 session-scoped runtime semantics。
- 为 host 暴露稳定的 invocation diagnostics，而不是继续让可见性判断停留在隐式逻辑中。
- 保持 `main-router` 继续承担 root routing agent 角色，但让它消费 resolved capability exposure。
- 保持现有 `SkillExecutor`、`AgentRuntime`、`ToolRuntime` 的主执行边界，不把 capability exposure 和 execution policy 再次耦合。

**Non-Goals:**

- 不实现完整 CLI slash UX。
- 不在本 change 中重写 `SkillExecutor` 或 skill policy semantics。
- 不在本 change 中直接实现完整 plugin marketplace 或 MCP product surface。
- 不要求第一阶段就用 generic invocation tool 取代 builtin `skill` tool。
- 不让 invocation layer 成为 capability escalation 入口。

## Decisions

### 1. 引入 `InvocationDefinition` / `InvocationProvider` / `InvocationRegistry`，而不是继续扩张 `SkillRegistry`

新增独立的 invocation catalog primitives：

- `InvocationDefinition`
- `InvocationProvider`
- `InvocationRegistry`
- `InvocationResolutionContext`
- `ResolvedInvocationCatalog`

skill 通过 adapter 映射为 invocation entry，而不是直接把 `SkillDefinition` 升级成大一统 definition。

Why:

- 当前缺口主要在暴露层，而不是 skill execution 层。
- 直接继续扩张 `SkillRegistry` 会把 skill-specific execution concerns 和 future source federation 混在一起。
- provider pipeline 比单个巨型 loader 更适合接后续 slash / plugin / MCP sources。

Alternatives considered:

- 直接把 `SkillRegistry` 升级成统一 command registry。拒绝，因为 skill 只是 invocation source 的一种，后续 source federation 会让 registry 语义混乱。

### 2. visibility policy 与 execution policy 显式分离

`InvocationDefinition` 中的 metadata 拆成两类：

- visibility policy
  - `user_invocable`
  - `model_invocable`
  - `paths`
  - help / argument hints
  - host surface hints
- execution policy
  - target kind
  - `allowed-tools`
  - `context`
  - `agent`
  - `model`
  - `effort`
  - `hooks`

`disable-model-invocation` 在 loader 兼容层保留，但 runtime 内部统一收敛为正向语义 `model_invocable`。

Why:

- 当前最缺的是“可见 / 可调”的可解释 contract，而不是执行 contract。
- 正向字段更利于 policy merge、diagnostics 和 host API。

Alternatives considered:

- 继续让 `SkillDefinition` 直接承载所有 visibility 与 execution 语义。拒绝，因为 host-facing catalog 与 execution backend 的关注点不同。

### 3. `paths` activation 迁移到 session-scoped resolution，不再停留在 registry 层

`paths` 的求值从 `SkillRegistry.resolve_active(paths=...)` 升级为 invocation resolution contract 的一部分。resolution context 至少可包含：

- 用户 prompt 中显式提及的路径
- attachments
- 当前 cwd / workspace roots
- 最近 turn 中工具观测到的路径
- host 显式传入的 working set

求值规则固定为：

- 不声明 `paths` 的 invocation：默认可见
- 声明 `paths` 且命中：可见
- 声明 `paths` 但无法证明命中：默认隐藏

Why:

- 这才符合 conditional activation 的语义。
- 当前在拿不到上下文时默认暴露 path-scoped skill，会和 spec 直接冲突。

Alternatives considered:

- 继续把 `paths` 仅作为 registry filter。拒绝，因为 registry 不拥有足够上下文来做 session-level visibility 决策。

### 4. `main-router` 不替代 invocation catalog，而是消费 resolved capability exposure

本 change 固定三层分工：

- Invocation / Capability layer
  - 决定什么能力当前可见、可调
- `main-router`
  - 决定本轮语义上走直答、tool、skill、还是 subagent
- `SkillExecutor` / `AgentRuntime` / `ToolRuntime`
  - 真正执行

Why:

- `main-router` 是 routing agent，不应承担 catalog / visibility resolution 的控制面职责。
- 把可见性逻辑继续塞给 `main-router` prompt，会让 runtime semantics 再次退化成 prompt-only behavior。

Alternatives considered:

- 让 `main-router` 直接基于原始 registries 做能力推断。拒绝，因为这会让 path activation 和 invocability semantics 继续不可验证。

### 5. 第一阶段保持 builtin `skill` tool 主路径不变

第一阶段只补齐 invocation catalog / visibility / diagnostics：

- user-facing 或 host-facing invocation surfaces 统一接 catalog
- skill execution 仍走现有 builtin `skill` tool + `SkillExecutor`
- 是否增加 generic invocation tool，留到第二阶段再评估

Why:

- 当前 `SkillExecutor` 已经是成熟 backend，重写收益小、风险高。
- 先稳定 catalog / resolution contract，再讨论模型调用 surface，更符合分层收敛顺序。

Alternatives considered:

- 立刻用 generic command / invocation tool 替代 builtin `skill` tool。当前不采用，因为这会扩大协议变更面并增加迁移复杂度。

### 6. diagnostics 必须是一等输出，而不是隐式副产品

runtime 将增加 host-facing diagnostics surface，用于回答：

- invocation 是否可见
- 是否允许用户调用
- 是否允许模型调用
- 被哪些 activation rule 隐藏
- 被哪些 policy ceiling 收窄或拒绝

Why:

- 这是 framework 比产品 runtime 更需要暴露的能力。
- 如果没有 diagnostics，host 很难构建稳定的 UI 或 debugging surface。

Alternatives considered:

- 仅通过日志或 trace 输出隐式诊断。拒绝，因为 host 无法稳定消费，也不利于测试。

## Risks / Trade-offs

- [visibility policy 与 execution policy 合并不清晰] → Mitigation: 在类型层显式拆分两类 policy，并对 diagnostics 输出使用同一套字段命名。
- [session resolution context 过宽，导致 host 行为分叉] → Mitigation: 固定最小 resolution inputs，并允许 host 明确传入 working set，而不是依赖隐式猜测。
- [phase 1 与现有 `skill` tool 并存，增加概念数量] → Mitigation: 在文档中明确“catalog 是暴露层，`skill` tool 是 execution backend”，避免把二者混为一谈。
- [future source federation 提前抽象过度] → Mitigation: 第一阶段只实现 skill adapter，并为 slash / plugin / MCP 定义最小 provider contract，不要求完整产品实现。

## Migration Plan

1. 引入 invocation catalog primitives 与 session-scoped resolution context。
2. 为 skill source 增加 adapter，把 `SkillDefinition` 投影为 `InvocationDefinition`。
3. 将 `paths`、`user-invocable`、`disable-model-invocation` 等字段接入 resolution 语义。
4. 增加 host-facing diagnostics surface。
5. 调整 root capability exposure，让 `main-router` 消费 resolved visible capabilities。
6. 后续再按 provider pipeline 接入 slash / plugin / MCP sources。

Rollback strategy:

- 若 provider pipeline 设计过重，可保留 skill adapter 与 session-scoped resolution contract，推迟 slash / plugin / MCP provider 的 public surface。
- 若 host-facing diagnostics API 需要调整，可先保留内部 diagnostics 结构，但不要回退到 registry-only visibility。

## Open Questions

- 第一阶段是否公开 `InvocationRegistry` 给 host，还是先只暴露 resolved catalog 查询接口？
- host 是否需要请求“隐藏条目 + 隐藏原因”的完整列表，还是默认只返回当前可见条目？
- `main-router` 在 prompt composition 中是否需要显式 `available_invocations`，还是暂时只消费已有 skills / tools / agents 视图？

## Appendix A: Naming / Glossary

- `SessionCommand`
  - host 输入事件归一化后的队列项
  - 负责 session control flow，而不是 capability exposure
- `Invocation`
  - 可由 host 或模型触发的 capability entry
  - 关注点是可见性、可调用性与诊断面
- `Skill`
  - execution-specific definition
  - 是 invocation source 的一种，但不是 catalog 本体
- `main-router`
  - root routing agent
  - 负责在“直答 / tool / skill / subagent”之间做语义路由
  - 不负责 resolution 或 visibility 判定
- `Execution backend`
  - `SkillExecutor`、`AgentRuntime`、`ToolRuntime`
  - 负责真正执行，不负责决定某项 capability 当前是否应暴露

## Appendix B: Data Model Sketch

### `InvocationDefinition`

- `name`
  - invocation 稳定标识
- `source_kind`
  - 例如 `builtin_skill`、`skill_dir`、`slash_command`、`plugin_command`、`mcp_prompt`
- `display_name`
  - host-facing 展示名称
- `description`
  - capability 摘要
- `argument_hint`
  - host 或模型可见的参数提示
- `visibility_policy`
  - `user_invocable: bool`
  - `model_invocable: bool`
  - `paths: tuple[str, ...]`
  - `surface_hints: dict[str, Any]`
- `execution_policy`
  - `target_kind`
  - `target_name`
  - `context`
  - `allowed_tools`
  - `agent`
  - `model`
  - `effort`
  - `hooks`
- `metadata`
  - source-specific raw payload 与扩展字段

### `InvocationResolutionContext`

- `session_id`
- `turn_id`
- `cwd`
- `prompt_paths`
  - 从当前 prompt 明确提取出的路径
- `attachments`
  - 当前 turn 附件或 host 传入材料
- `workspace_roots`
  - 当前可见工作区根目录
- `observed_paths`
  - 最近 tool/file observation 暴露出的路径
- `working_set`
  - host 显式提供的路径集合

### `ResolvedInvocationCatalog`

- `visible`
  - 当前 session context 下可见的 invocation entries
- `hidden`
  - 当前被隐藏的 invocation entries 及其 diagnostics
- `diagnostics`
  - lookup-friendly 诊断索引，供 host / tests 查询

### `InvocationDiagnostics`

- `visible: bool`
- `user_invocable: bool`
- `model_invocable: bool`
- `hidden_reason`
  - 例如 `path_mismatch`、`path_indeterminate`、`user_disabled`、`model_disabled`
- `matched_paths`
  - 已命中的 activation paths
- `path_match_state`
  - `matched`、`not_matched`、`indeterminate`
- `narrowed_by_policy`
  - capability ceilings 或 execution policy 的收窄说明

## Appendix C: Resolution Algorithm

session-scoped invocation resolution 固定按以下顺序执行：

1. Collect entries
   - 从已注册的 invocation providers 收集原始 entries
   - 保留 source identity，不在这一层丢失来源
2. Normalize metadata
   - 将 `disable-model-invocation` 收敛为 `model_invocable`
   - 统一 `paths`、argument hints 与 source-specific booleans
3. Build resolution context
   - 汇总 `prompt_paths`、attachments、workspace roots、observed paths 与 host working set
4. Evaluate path activation
   - 若未声明 `paths`，直接标记为 `matched`
   - 若声明了 `paths` 且已证明命中，标记为 `matched`
   - 若声明了 `paths` 且已证明不命中，标记为 `not_matched`
   - 若声明了 `paths` 但当前上下文不足以判断，标记为 `indeterminate`
5. Compute visibility
   - `matched` → entry 可见
   - `not_matched` → entry 隐藏，hidden reason 为 `path_mismatch`
   - `indeterminate` → entry 默认隐藏，hidden reason 为 `path_indeterminate`
6. Compute invocability
   - 在可见性之后独立计算 `user_invocable` 与 `model_invocable`
   - 二者必须分别保留，不得折叠成单一 enabled flag
7. Preserve execution ceilings
   - invocation layer 只能携带或解释 execution policy，不能扩大 parent / skill / agent ceilings
8. Emit catalog and diagnostics
   - 输出 visible entries
   - 输出 hidden / disabled entries 的 diagnostics，供 host、tests 与 future UI 使用
