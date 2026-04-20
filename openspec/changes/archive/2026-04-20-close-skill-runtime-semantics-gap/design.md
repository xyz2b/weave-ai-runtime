## Context

当前 runtime 已经具备 skill 的基础骨架：

- `DefinitionDiscovery` 能从 `SKILL.md` 解析参考实现风格 frontmatter
- `SkillExecutor` 能执行 inline 与 forked skill，并接入 permission / hook / isolation control plane
- `InvocationCatalog` 能基于 `paths`、`user-invocable`、`disable-model-invocation` 与 policy narrowing 计算可见性
- `ToolOrchestration` 已经记录 `observed_paths`，并具备 capability refresh 基础设施
- `SessionController` 已经具备 session-private runtime metadata 通道

本设计采用一个明确前提：skill 的本体是 `prompt body + typed metadata + runtime policy envelope`。

- `prompt body`：`SKILL.md` 的正文，以及执行前的参数替换、session 变量替换和 shell block expansion
- `typed metadata`：frontmatter 中的 `paths`、`user-invocable`、`disable-model-invocation`、`shell`、`model`、`effort`、`allowed-tools` 等声明
- `runtime policy envelope`：这些 metadata 在运行时派生出的 activation、visibility、tool narrowing、request shaping、hook ownership 与 fork/delegation 约束

为避免再次退化成“字段已解析但未生效”，本变更对关键 frontmatter 字段采用下面这张固定映射表：

| Field | 所属层 | Runtime owner | 生效时机 | 失败/诊断表现 |
| --- | --- | --- | --- | --- |
| `allowed-tools` | typed metadata -> runtime policy | `SkillExecutor` + `ExecutionPolicy` | skill invocation、inline tool use、forked delegation | tool/skill 因 execution policy 被拒绝，并保留 policy trace |
| `model` | typed metadata -> runtime policy | `SkillRequestOverrideState` + `TurnEngine` / `AgentRuntime` | inline 后续请求、forked child invocation | 无法解析或不可用的 override 以 request / child invocation error surfaced |
| `effort` | typed metadata -> runtime policy | `SkillRequestOverrideState` + `TurnEngine` / `AgentRuntime` | inline 后续请求、forked child invocation | discovery 阶段拒绝非法值；运行期保留 request metadata |
| `hooks` | typed metadata -> runtime policy | `SkillExecutor` + hook bus | skill invocation 生命周期内 | hook registration / permission denial 进入 hook diagnostics |
| `context` | typed metadata -> runtime policy | `SkillExecutor` | skill execution dispatch | `inline` 注入消息；`fork` 委派 child run |
| `agent` | typed metadata -> runtime policy | `SkillExecutor` + `AgentRuntime` | forked skill child selection | unknown agent surfaced as invocation failure |
| `paths` | typed metadata -> runtime policy | `InvocationCatalog` + session dynamic skill view | discovery、visibility、explicit invocation eligibility | hidden reason / path-match diagnostics / activation denial |
| `user-invocable` | typed metadata -> runtime policy | `InvocationCatalog` + host execution gate | host-visible query、显式用户调用 | host surface 隐藏或 explicit invocation rejected |
| `disable-model-invocation` | typed metadata -> runtime policy | `InvocationCatalog` + `TurnEngine` skill pool resolution | model-visible skill pool 构建 | host-visible 但 model-invocable=false |
| `shell` | typed metadata -> prompt body + runtime policy | `SkillPromptExpander` + shell tool path | local skill prompt expansion | permission denied / timeout / non-zero exit surfaced as skill expansion failure |

但剩余缺口仍然明显：

- `shell` 只被解析，未进入任何执行路径
- skill 级别 `effort` 对 inline/forked 执行都没有稳定 runtime effect；`model` 只在 forked path 部分生效
- runtime 只加载固定 user/project skill roots，缺少参考实现风格基于路径的 nested `.runtime/skills` 动态发现
- invocation visibility、model skill pool、host-visible skill surfaces 仍然共享事实来源不足，容易继续漂移

这个变更需要补的是“剩余运行时语义”，不是重写 skill 子系统。

## Goals / Non-Goals

**Goals:**

- 让 skill frontmatter 中当前仍是 metadata-only 的字段变成真实 runtime semantics
- 为 nested `.runtime/skills` 提供基于当前会话工作集路径的动态发现与优先级合并
- 让 inline skill 与 forked skill 都能应用 skill 级别的 model / effort override
- 为 local skill 补齐参考实现风格 prompt shell expansion，并复用现有 permission / tool execution 路径
- 将 skill visibility、activation、policy narrowing 与 diagnostics 收敛到同一套判定结果

**Non-Goals:**

- 不在本变更中引入新的远程 skill source 或 MCP skill transport
- 不重新设计 `ToolDefinition` / `SkillDefinition` 的外部格式
- 不在本变更中实现新的 sandbox 或 shell permission 模型；继续复用现有 permission / isolation control plane
- 不追求参考实现的 TUI 层面的完全同构；本变更只覆盖 runtime semantics

## Decisions

### 1. 使用 session-scoped dynamic skill roots，而不是直接修改全局 SkillRegistry

动态发现的 nested `.runtime/skills` roots 将以 session-scoped root ledger 的形式保存在 session private context 中，而不是直接常驻修改全局 `SkillRegistry`。

实现方式：

- 在 session metadata / private context 中记录 `skill_dynamic_roots`
- 在 runtime kernel 中增加基于 root path 的 definition cache，缓存每个 discovered root 解析出的 skill definitions
- 每轮 turn 构建 skill 视图时，将 base registry 与 session dynamic roots 合并，生成本轮有效 skill set
- 合并时按 `(source priority, root specificity)` 排序，让更深层的 project-local root 覆盖更浅层 root

Why:

- 动态发现应当是 session-local 行为，不能污染其他 session
- 现有 `DefinitionRegistry` 只按 source priority 处理冲突，不足以表达“更近路径优先”的参考实现语义
- 保持全局 registry 只承载静态定义，session overlay 处理动态来源，边界更清晰

Alternatives considered:

- 直接把动态 skill 注册进全局 `SkillRegistry`。拒绝，因为会引入跨 session 泄漏与同名冲突。
- 修改 `DefinitionRegistry` 为全局支持 path depth precedence。拒绝，因为会把 session-local precedence 规则扩散到所有 definition 类型。

### 2. activation lifecycle 以“发现 roots + 上下文匹配”派生，不再引入第二套全局激活表

path-scoped skill 的 activation 将继续基于 `prompt_paths`、`attachments`、`observed_paths`、`working_set` 计算，但会叠加 session 已发现的 dynamic roots，并扩展诊断结果。

实现方式：

- `InvocationCatalog` 在现有 path matching 基础上，新增对 discovered roots / source specificity 的感知
- `observed_paths` 继续作为跨 turn 的单调证据来源
- 诊断面显式区分：
  - skill 是否已被发现
  - path 是否匹配
  - 是否被 policy narrowing 屏蔽
  - 是否仅 host-visible / user-visible / model-visible

Why:

- 当前 runtime 已经有 `observed_paths` 历史与 session metadata，不需要再维护一套独立 skill-name activation ledger
- 派生式 activation 更容易与 compaction、replay、diagnostics 对齐

Alternatives considered:

- 新增 `activated_skill_names` 持久表并显式写入/移除。拒绝，因为这会复制已有 path/history 事实，并增加状态漂移风险。

### 3. 将 skill request-shaping state 与 capability policy state 分开

`ExecutionPolicy` 继续负责 capability ceiling；skill 级别的 `model` / `effort` override 则进入独立 request-shaping state。

实现方式：

- 新增 `SkillRequestOverrideState`，承载：
  - `requested_model`
  - `requested_effort`
  - `source_skill`
- inline skill 执行时由 `SkillExecutor` 更新 override state
- `TurnEngine` 构建 `ModelRequest` 时优先读取 override state，再回退到 agent-level `model` / `effort`
- forked skill 在 `AgentInvocation` 上新增 `requested_effort`，与现有 `requested_model` 对齐

Why:

- `model` / `effort` 是 request-shaping 语义，不是 capability ceiling
- 如果把它们塞进 `ExecutionPolicy`，会模糊安全边界与请求形状的职责划分
- 这样 skill 的 runtime policy 可以明确拆成两部分：capability policy 和 request-shaping policy，各自有稳定承载点

Alternatives considered:

- 扩展 `ExecutionPolicy` 直接承载 `model` / `effort`。拒绝，因为它会把安全约束和请求形状耦合在一起。
- 只在 `SkillExecutionResult` 里返回 override，不进入 shared state。拒绝，因为 turn engine 下一轮请求构建无法统一消费。

### 4. request override 与 activation 使用显式生命周期和优先级规则

skill 的 request override 与 activation evidence 采用固定生命周期规则，而不是由调用点隐式决定。

实现方式：

- inline skill 产生的 `model` / `effort` override 为 consume-once state：在下一次 `ModelRequest` 构建前保持有效，请求发出后立即清空
- 若同一 turn 在请求构建前连续触发多个 inline skill，则按字段维度 last explicit write wins
  - 后触发 skill 只覆盖它显式声明的字段
  - 未声明的字段保留之前 pending override 或回退 agent default
- forked skill 的 `model` / `effort` override 只作用于 child invocation，不回写 parent 的 pending override state
- dynamic roots 与 observed path evidence 对当前 session 持续有效，并在 transcript resume 后恢复；它们不会泄漏到其他 session
- merged skill view 保持现有 source-priority contract 不变；仅在同一 source class 内新增“更深 root 优先于更浅 root”的规则

Why:

- request override 若没有显式生命周期，很容易在多 skill turn 中产生幽灵状态
- activation evidence 若不跨 turn / resume 持续，path-scoped skill 的行为会与参考实现明显偏离
- precedence 必须写死，否则 dynamic roots 一进入就会让 shadowing 规则变得不可预测

Alternatives considered:

- 让 inline override 持续到 turn 结束甚至会话结束。拒绝，因为它会让 skill request shaping 难以推理且不利于组合。
- 让 dynamic roots 只在当前 turn 生效。拒绝，因为这会让 skill activation 丢失“已观测工作集”语义。

### 5. 为 skill 增加独立的 prompt expander，并复用现有 shell tool 路径

skill 内容渲染将收敛到一个单独的 `SkillPromptExpander`，负责变量替换与 shell expansion。

实现方式：

- 在 `SkillExecutor` 中调用 expander，而不是直接做字符串替换
- expander 负责：
  - `$ARGUMENTS`
  - `${ARG1...}`
  - `${CLAUDE_SESSION_ID}`
  - `${CLAUDE_SKILL_DIR}`
  - 参考实现风格 `!` inline / fenced shell blocks
- shell expansion 通过现有 `shell` tool 执行，遵守当前 `tool_pool`、permission、progress 与 telemetry 路径
- `shell:` frontmatter 只选择执行 shell，不绕过现有 permission model

Why:

- 这样 `shell` frontmatter 才会成为 runtime contract，而不只是定义字段
- 复用现有 shell tool 能保持 permission / observability 一致
- 这也让 `prompt body` 成为一个独立、可测试的 skill 本体层，而不是散落在 `SkillExecutor` 中的字符串处理

Shell safety contract:

- 只有 file-backed local skill source 允许 shell expansion；未来 remote / MCP / untrusted source 默认禁止
- shell block expansion 必须通过现有 shell tool path 执行，不能直接启动 subprocess
- shell expansion 遇到 permission denied、timeout 或 non-zero exit 时采用 fail-fast 语义，不注入 partial prompt
- shell execution 产生的 telemetry、tool lifecycle、observed paths 与 permission trace 必须沿用现有 shell tool 通道

Alternatives considered:

- 直接在 expander 中启动 subprocess。拒绝，因为会绕过 tool runtime 与 permission control plane。
- 只做变量替换，不实现 shell expansion。拒绝，因为这会继续保留已解析未生效字段。

### 6. invocation gate 统一由 catalog decision 驱动

skill 的 user-visible、model-visible、policy-visible 将由同一个 resolved decision 结构驱动，避免 host surface 与 model skill pool 再次分叉。

实现方式：

- `InvocationCatalog` 生成更完整的 resolved decision / diagnostics
- `visible_capabilities()` 与 `visible_skill_definitions()` 从同一批 decision 派生
- `TurnEngine` 只消费 `model_invocable=True` 的 resolved skill set
- host-facing queries 只消费 `user_invocable=True` 的 resolved capability set

Why:

- 当前逻辑虽然已部分统一，但 model pool、host surface、diagnostics 的组合仍然分散
- 把 gate 集中到 catalog，有利于回归测试与后续 archive 稳定性
- 这样 `typed metadata` 到 `runtime policy envelope` 的映射就有单一事实来源，而不是由多个调用点各自解释

Alternatives considered:

- 继续让 `TurnEngine`、`SessionController` 与 host 查询各自解释 `user-invocable` / `disable-model-invocation`。拒绝，因为这会持续产生漂移。

### 7. 扩展 capability refresh，从 `tool_pool` 扩展到 `skill_pool` / invocation surfaces

动态 skill discovery 需要在文件观测后尽快进入下一轮 turn，而不是等下一次新会话或手工重建。

实现方式：

- 扩展现有 capability refresh 事件，使其支持 `skill_pool` 或 `invocations` scope
- 文件相关工具在记录 `observed_paths` 后，可请求 skill refresh
- refresh callback 只更新本 session 的 dynamic roots / effective skill view，不修改全局 registry

Why:

- 这允许“读到某个子目录文件后，同一工作回合就看到该目录 skill”的语义
- 复用现有 refresh infrastructure，避免新增第二套刷新通道

Alternatives considered:

- 只在下一次 turn 重新发现 skill。拒绝，因为这会让动态 skill discovery 体验滞后于参考实现。

## Implementation Contracts

这一节故意把设计补到“实现约束级”，用于减少 AI 落地时的自由发挥，但不规定具体函数拆分或 patch 形状。

### Module ownership

| Concern | Primary modules | Supporting modules | Hard constraints |
| --- | --- | --- | --- |
| Dynamic root discovery and session overlay | `session_runtime/controller.py`, `runtime_kernel/kernel.py`, `registries/discovery.py` | `registries/skill_registry.py`, `invocation_catalog.py` | discovered roots 只能作为 session-local overlay 存在，不能直接常驻写入全局 `SkillRegistry` |
| Activation, visibility, and invocation gates | `definitions.py`, `invocation_catalog.py`, `turn_engine/engine.py` | `runtime_kernel/kernel.py`, `session_runtime/controller.py` | host-visible、model-visible、explicit execution gate 必须共用同一份 resolved decision |
| Request-shaping override state | `skill_runtime.py`, `turn_engine/engine.py`, `agent_runtime.py` | `contracts.py` | `model` / `effort` 不能并入 `ExecutionPolicy`；fork child override 不得回写 parent pending state |
| Prompt expansion and shell execution | `skill_runtime.py` 或相邻 expander 模块 | `tool_orchestration.py`, shell tool execution path | shell block 只能走现有 shell tool path，不能走 direct subprocess shortcut |
| Resume-safe state restoration | `session_runtime/controller.py`, `contracts.py` | `runtime_kernel/kernel.py`, `invocation_catalog.py` | transcript / session metadata 里只存可序列化 summary，不存完整 `SkillDefinition` 对象 |

### State contracts

内部实现可以采用 typed helper / dataclass，但跨模块 transport 与 transcript-compatible carrier 采用下面这套固定合同。

| Carrier | Canonical key / field | Written by | Read by | Lifetime / constraints |
| --- | --- | --- | --- | --- |
| `SessionState.metadata` 与 `RuntimePrivateContext.extensions` | `skill_dynamic_roots` | session refresh / discovery path | merged skill view builder、`InvocationCatalog` | value 是 serializable root records 列表，至少包含 `root`、`source`、`discovered_from`；路径必须是 normalized absolute path 且位于 session cwd 下 |
| `SessionState.metadata` 与消息 metadata | `observed_paths` | `ToolOrchestration` file observation path | `build_invocation_resolution_context()` | 继续作为 activation evidence 单一事实来源；不新增平行的 `activated_skill_names` 表 |
| `RuntimePrivateContext.extensions` | `skill_request_override` | inline `SkillExecutor` | `TurnEngine` request builder | serialized shape 固定包含 `requested_model`、`requested_effort`、`source_skill`；成功 shaping 一次请求后立即清空 |
| `AgentInvocation` | `requested_model`、`requested_effort` | forked `SkillExecutor` | child `AgentRuntime` / `TurnEngine` | child-only request shaping；不得回写 parent `skill_request_override` |
| runtime-kernel local cache | root path -> parsed skill report | discovery refresh path | merged skill view builder | process-local only；不写 transcript，不写 session metadata |

### Execution surface matrix

| Surface | Eligibility predicate | Enforcement point | Failure behavior |
| --- | --- | --- | --- |
| Host-visible invocation listing | `resolved.visible && resolved.capability.user_invocable` | `ResolvedInvocationCatalog.visible_capabilities(user_invocable=True)` | 从 host surface 隐藏，但保留 diagnostics |
| Model skill pool | `resolved.visible && resolved.capability.model_invocable` | `_resolve_iteration_skill_pool()` in `turn_engine/engine.py` | 不进入 model request 的可用 skill pool |
| Explicit user-originated skill execution | skill 存在于 resolved catalog，且 `visible=true`、`user_invocable=true`、`path_match_state=MATCHED` | host / session execution gate，在调用 `SkillExecutor.execute()` 前 | reject，并优先复用 catalog diagnostic 构造错误原因 |
| Model-driven skill execution | skill 存在于 resolved catalog，且 `visible=true`、`model_invocable=true`、未被 policy narrowing 排除 | model invocation resolver / skill execution entrypoint | reject，并保留 policy or visibility diagnostics |

### Call-chain contracts

#### A. Dynamic discovery and activation

1. 文件相关工具通过 `ToolOrchestration` 继续记录 `observed_paths`。
2. capability refresh 扩展为支持 `skill_pool` 或 `invocations` scope。
3. session refresh path 从新观测到的 workspace path 向上去重发现 `.runtime/skills` roots，并更新 `skill_dynamic_roots`。
4. merged skill view 基于 base registry + session dynamic roots 构建，再交给 `InvocationCatalog` 计算 visibility / diagnostics。
5. host-visible、model-visible、explicit invocation gate 一律消费同一份 resolved catalog。

#### B. Inline request override

1. `SkillExecutor.execute()` 解析 skill、解析 policy、完成 prompt expansion。
2. inline path 除了返回 injected message，还必须返回或写入 `skill_request_override` private update。
3. `TurnEngine` 在 private context merge 阶段接收该 override。
4. 下一次 `ModelRequest` 构建时优先读取 override，并按字段覆盖 agent default。
5. 请求真正发出后，`TurnEngine` 立即清空 pending override，避免后续请求幽灵继承。

#### C. Forked request override

1. forked skill 完成 prompt expansion 后构造 child `AgentInvocation`。
2. child invocation 显式携带 `requested_model` 与新增的 `requested_effort`。
3. child run 将这些值作为初始 request-shaping 输入。
4. parent session 的 pending `skill_request_override` 保持不变。

#### D. Prompt expansion and shell execution

1. `SkillPromptExpander` 负责 `$ARGUMENTS`、`${ARG1...}`、`${CLAUDE_SESSION_ID}`、`${CLAUDE_SKILL_DIR}` 和 shell block parsing。
2. 只有 file-backed local skill source 允许进入 shell expansion。
3. shell block 通过现有 shell tool path 执行，并沿用当前 permission、progress、telemetry、observed-path 更新通道。
4. 任一 block 出现 permission denied、timeout 或 non-zero exit 时，整个 skill expansion fail closed，不注入 partial output。

### Rule tables

#### Skill precedence

| Case | Rule |
| --- | --- |
| 同名 skill，source class 不同 | 继续沿用现有 `DefinitionOrigin.priority()` 结果 |
| 同名 skill，source class 相同，但 root 深度不同 | 更深 root 胜出 |
| 同名 skill，source class 与 root 都相同 | 继续视为同一来源冲突，保持现有 registry/definition conflict 语义 |

#### Request override

| Case | Rule |
| --- | --- |
| 单个 inline skill 同时声明 `model` 和 `effort` | 两个字段都作用于下一次 request，仅一次 |
| 后一个 inline skill 只声明 `effort` | 覆盖 pending `effort`，保留 pending `model` |
| 多个 inline skill 在下一次 request 前连续触发 | field-level last explicit write wins |
| forked skill 声明 override | 仅作用于 child invocation，不改 parent pending state |

#### Shell expansion failure handling

| Case | Rule |
| --- | --- |
| source 不是 file-backed local skill | 不执行 shell block，作为 expansion error surfaced |
| shell tool permission denied | fail closed，不注入任何 partial shell output |
| shell block timeout / non-zero exit | fail closed，并通过正常 tool / skill error channel surfaced |
| shell block 成功但 stdout 为空 | 允许注入空结果，不视为失败 |

### Test mapping

| Capability area | Primary tests | Must prove |
| --- | --- | --- |
| discovery / root merge | `tests/test_discovery.py` | nested root discovery、same-name shadowing、resume-safe root persistence |
| activation / diagnostics / gate | `tests/test_invocation_catalog.py` | path mismatch、policy narrowing、host-visible vs model-visible split、explicit invocation rejection reasons |
| inline / fork runtime semantics | `tests/test_agent_skill_runtime.py` | inline consume-once override、fork child override propagation、shell expansion success and fail-closed behavior |

## Risks / Trade-offs

- **[动态发现带来额外文件系统开销]** → Mitigation: 对 walked paths 和 discovered roots 做去重，并在 runtime kernel 中缓存 root-level discovery 结果。
- **[shell expansion 可能绕出既有 permission 语义]** → Mitigation: shell expansion 必须通过现有 `shell` tool 执行，禁止直接 subprocess 快捷路径。
- **[session overlay 与 base registry 可能出现 precedence 歧义]** → Mitigation: 明确 `(source priority, root specificity)` 规则，并为同名 skill shadowing 增加测试。
- **[request override state 与 policy state 漂移]** → Mitigation: 分别定义稳定 metadata key，并在 turn build / skill execution 两侧只通过统一 helper 读写。
- **[dynamic roots 被错误序列化进 transcript]** → Mitigation: session metadata 只保存 root path 和 summary，不保存完整 `SkillDefinition` 对象。

## Migration Plan

1. 新增 session-scoped dynamic skill root ledger 与 root discovery cache。
2. 让 turn engine 能从 session roots 构建 merged skill view，并将其接入 invocation catalog。
3. 增加 request override state，并让 `ModelRequest` / forked `AgentInvocation` 消费 skill 级别 `model` / `effort`。
4. 引入 `SkillPromptExpander`，补齐变量替换与 shell expansion 语义。
5. 扩展 capability refresh 与 tests，覆盖 nested discovery、shadowing、override、shell expansion 与 diagnostics。

Rollback strategy:

- 若 dynamic discovery 或 shell expansion 的第一版存在风险，可保留静态 registry 与纯变量替换路径作为 fallback，同时禁用 dynamic roots 合并与 shell blocks 执行；这样不会影响现有已工作的 skill policy / isolation 语义。

## Open Questions

- host-facing diagnostics 中是否需要暴露 shell block 原文，还是只暴露 redacted summary / matched skill / affected paths？
