# tool-runtime-capability-contract Specification

## Purpose
TBD - created by archiving change add-streaming-tool-runtime-control-plane. Update Purpose after archive.
## Requirements
### Requirement: Tool definitions expose input-aware execution semantics
The runtime SHALL allow tool definitions to describe execution semantics that can depend on normalized tool input, including read-only classification, concurrency safety, interrupt behavior, failure policy, and optional host-facing presentation metadata.

#### Scenario: 工具并发语义依赖输入
- **WHEN** 某个工具在不同输入下可能表现为只读或变更型操作
- **THEN** runtime SHALL 在工具输入规范化后根据该输入解析实际 execution semantics，而不是只依赖静态 trait

### Requirement: Tool execution semantics resolve into a stable call-scoped snapshot
The runtime SHALL resolve `ToolExecutionSemantics` only after schema normalization, validation, pre-tool input rewriting, and any permission-mediated input updates have settled, and SHALL reuse the resulting call-scoped semantics snapshot across orchestration, permission logging, host presentation, classifier input generation, and tool result mapping.

#### Scenario: scheduler 与 UI 共享同一份 resolved semantics
- **WHEN** a tool call input is normalized and then rewritten by hooks before execution
- **THEN** runtime SHALL derive one resolved execution-semantics snapshot from the rewritten input and SHALL use that same snapshot for scheduling and host-visible tool presentation

#### Scenario: permission updatedInput 参与最终 semantics 求值
- **WHEN** permission resolution rewrites the execution-bound input for a tool call before execution starts
- **THEN** runtime SHALL derive the final resolved execution-semantics snapshot from that updated execution-bound input rather than from the pre-permission input

### Requirement: Tool call lifecycle is modeled through explicit lifecycle objects
The runtime SHALL model each tool call through at least three explicit lifecycle objects named `ToolCallEnvelope`, `ResolvedToolCall`, and `ToolOutcome`.

#### Scenario: streamed tool_use 首先生成 envelope
- **WHEN** the runtime observes a streamed or buffered `tool_use` for a turn
- **THEN** runtime SHALL first create a `ToolCallEnvelope` that captures the stable tool-use identifier, raw input, and arrival ordering before execution resolution begins

### Requirement: Resolved tool calls freeze final execution input and scheduling metadata
The runtime SHALL construct `ResolvedToolCall` only after all input-mutating phases and pre-execution authorization for that call have settled, and SHALL include the final execution-bound input, resolved execution semantics when available, capability context, scheduler disposition, and replay ordering metadata.

#### Scenario: resolved call 串联 semantics、capability 和 lane
- **WHEN** a tool call becomes ready for scheduling
- **THEN** runtime SHALL represent it as a `ResolvedToolCall` that carries the final execution input, resolved semantics, capability container, scheduler lane assignment, and replay index for that call

#### Scenario: permission deny 仍然留下 resolved call
- **WHEN** a tool call is denied during permission mediation before execution starts
- **THEN** runtime SHALL still materialize a `ResolvedToolCall` with explicit resolution status, permission decision, and replay metadata for that call even if no executable scheduler lane is assigned

### Requirement: Resolved tool calls record structured permission decisions
The runtime SHALL model the result of permission mediation as a structured `ResolvedPermissionDecision` attached to `ResolvedToolCall`, including at least the effective allow-or-deny behavior, any execution-bound `updated_input`, and any host-visible feedback content needed by later replay or host observation.

#### Scenario: permission updatedInput 被冻结到 resolved call
- **WHEN** permission mediation returns an `updatedInput` that differs from the post-hook input
- **THEN** runtime SHALL record that structured permission decision on `ResolvedToolCall` and SHALL treat the updated input as the execution-bound input for later semantics resolution and execution

### Requirement: Resolved permission decisions form a closed terminal union
The runtime SHALL model `ResolvedPermissionDecision` as a closed terminal union with explicit allow and deny variants, and SHALL NOT expose unresolved prompt states such as `ask` or `pending` after `ResolvedToolCall` has been materialized.

#### Scenario: resolved permission decision 不保留 ask 中间态
- **WHEN** permission mediation required interactive prompting before a tool call could be resolved
- **THEN** the resulting `ResolvedPermissionDecision` attached to `ResolvedToolCall` SHALL still be terminal `allow` or terminal `deny` rather than an intermediate prompt state

#### Scenario: deny variant 足以直接生成终态 outcome
- **WHEN** a tool call is denied before execution begins
- **THEN** the deny variant of `ResolvedPermissionDecision` SHALL contain sufficient terminal information for runtime to construct the denied or cancelled terminal outcome without re-entering the permission engine

### Requirement: Tool outcomes are the terminal record consumed by replay and host observation
The runtime SHALL represent terminal tool completion, denial, cancellation, or failure as `ToolOutcome` objects linked to their originating `ResolvedToolCall`, and SHALL use those outcomes as the source of ordered replay and host-visible terminal tool state.

#### Scenario: ordered replay 消费 ToolOutcome
- **WHEN** multiple tool calls complete out of order
- **THEN** runtime SHALL use the `ToolOutcome` replay metadata from those completed calls to determine when each tool result becomes eligible for ordered replay

### Requirement: Tool outcomes carry structured context updates
The runtime SHALL represent non-result side effects from tool execution as structured `ContextUpdate` records attached to `ToolOutcome` rather than requiring replay, host adapters, or tests to interpret opaque runtime closures or unstructured metadata blobs.

#### Scenario: capability refresh 作为结构化 context update 暴露
- **WHEN** a tool execution requests a capability refresh that should affect later turns
- **THEN** runtime SHALL record that request as a structured `ContextUpdate` on the terminal `ToolOutcome` so the shared control plane and tests can observe it deterministically

### Requirement: Context updates form a closed typed union with explicit apply phases
The runtime SHALL model `ContextUpdate` as a closed typed union whose variants declare their apply phase explicitly, and SHALL use those phases to distinguish updates that may apply before replay, with replay, or only after replay commit.

#### Scenario: transcript-visible attachment 必须和 replay slot 对齐
- **WHEN** a tool outcome carries a transcript attachment or equivalent host-visible artifact that should remain aligned with a terminal `tool_result`
- **THEN** runtime SHALL represent it as a `ContextUpdate` variant whose apply phase is `with_replay`

#### Scenario: long-lived state mutation 延后到 replay 之后
- **WHEN** a tool outcome carries a memory append or equivalent long-lived state mutation
- **THEN** runtime SHALL support representing it as a `ContextUpdate` variant that applies only after replay commit succeeds

#### Scenario: legacy 闭包 side effect 只能走兼容 variant
- **WHEN** a legacy tool or adapter still produces a closure-style context modifier
- **THEN** runtime SHALL wrap it in an explicit compatibility `ContextUpdate` variant rather than treating arbitrary closures as the primary structured side-effect model

### Requirement: Tool execution semantics can provide presentation and classifier data
The runtime SHALL allow tool execution semantics to provide tool-use presentation, tool-result summary, and classifier input derived from the same normalized call semantics.

#### Scenario: classifier 与 tool summary 使用一致语义
- **WHEN** runtime needs both a classifier-oriented description and a user-facing summary for the same tool call
- **THEN** runtime SHALL derive both from the same resolved tool execution semantics rather than from unrelated ad-hoc formatting logic

### Requirement: Tool failure policy covers both outcome classification and sibling impact
The runtime SHALL model tool failure policy as a call-scoped structure that determines how tool outcomes are classified as failures and how such failures affect running siblings, queued siblings, and the in-flight model stream.

#### Scenario: failure policy 同时决定失败判定与 sibling 影响
- **WHEN** a tool call returns a result that may be considered failed under the resolved semantics for that call
- **THEN** runtime SHALL use the resolved failure policy both to classify the outcome and to determine whether sibling calls or the model stream must be cancelled or blocked

### Requirement: Tool execution receives an explicit capability container
The runtime SHALL provide each tool execution with a turn-scoped capability container that explicitly exposes `tool_catalog`, `agent_catalog`, `skill_catalog`, `permission_context`, `query_context`, `app_state`, `file_state`, `progress`, `notifications`, `refresh_capabilities`, and `memory_access`.

#### Scenario: 工具在执行中请求进度与 capability refresh
- **WHEN** 某个工具在执行过程中发出进度更新或请求刷新可用 capabilities
- **THEN** runtime SHALL 通过 tool context 暴露对应 capability，并 SHALL 将这些请求交给共享 control plane 处理

#### Scenario: 工具通过 query context 读取当前 turn 信息
- **WHEN** a tool needs the current session, turn, working directory, or current message snapshot
- **THEN** runtime SHALL expose those values through `query_context` rather than requiring the tool to read them from unstructured metadata

### Requirement: Tool executions receive a call-scoped capability view
The runtime SHALL derive the execution-time capability object passed to a tool from the turn-scoped capability container, and SHALL freeze call-scoped metadata including the tool-use identifier, replay index, canonical tool name when available, and selected executor tier for that execution.

#### Scenario: 同一 turn 的 capability 句柄保持共享但 call metadata 冻结
- **WHEN** two tool calls execute within the same turn
- **THEN** runtime SHALL allow them to share the same underlying turn-scoped capability handles while still exposing distinct frozen call-scoped metadata for each execution

### Requirement: Query context exposes executor tier and model capability profile
The runtime SHALL expose the selected tool executor tier and the normalized model capability profile for the current turn through `query_context`.

#### Scenario: tool 根据当前 executor tier 调整行为
- **WHEN** a tool needs to know whether the current turn is executing under full streaming, buffered, batch, or no-tool mode
- **THEN** runtime SHALL expose that information through `query_context` rather than requiring provider-specific branching inside the tool

### Requirement: Catalog capabilities expose alias-aware read-only views
The runtime SHALL expose `tool_catalog`, `agent_catalog`, and `skill_catalog` as read-only catalog views that are filtered by the active execution policy and support canonical lookup without exposing unrestricted global registries.

#### Scenario: tool catalog 通过 alias 解析 canonical tool
- **WHEN** a tool needs to inspect whether another tool is currently visible under the active execution policy using either its canonical name or an alias
- **THEN** runtime SHALL allow that lookup through the read-only `tool_catalog` view and SHALL resolve aliases without requiring direct registry access

#### Scenario: catalog 不暴露无界全局 registry
- **WHEN** a tool enumerates the available tools, agents, or skills during a turn
- **THEN** the exposed catalog views SHALL reflect only the policy-filtered visible entries for that turn rather than the unrestricted global registries

### Requirement: Permission context is a read-only effective authorization view
The runtime SHALL expose `permission_context` as a read-only view of the effective permission mode, prompt affordances, and visible rules for the current turn, while keeping actual authorization decisions inside the runtime permission engine.

#### Scenario: tool 观察当前 turn 是否允许交互式权限提示
- **WHEN** a tool needs to know whether the current execution mode allows interactive permission prompts or bubbles them to the caller
- **THEN** runtime SHALL expose that information through `permission_context` without requiring the tool to inspect internal host or permission-engine objects

#### Scenario: tool 不能通过 permission_context 自行放行
- **WHEN** a tool observes that the current `permission_context` appears permissive for a requested action
- **THEN** runtime SHALL still require the actual authorization decision to be evaluated by the runtime permission engine rather than treating the read-only context as direct approval

### Requirement: Standard tool capabilities are not accessed through raw runtime service bags
The runtime SHALL NOT require tools to reach raw runtime service containers or unstructured metadata in order to access standard catalog, query, state, progress, notification, refresh, or memory capabilities.

#### Scenario: tool 无需直接访问 runtime_services
- **WHEN** a tool needs a standard runtime capability such as progress emission or memory access
- **THEN** runtime SHALL provide that capability through the explicit tool capability container rather than through a raw `runtime_services` object

### Requirement: Tool lifecycle transitions remain observable
The runtime SHALL expose lifecycle transitions from envelope observation through replay commit as turn-scoped events or equivalent observable state transitions so hosts and conformance tests can distinguish observation, resolution, execution start, terminal outcome recording, and replay commit.

#### Scenario: host 可以观测 envelope 到 replay 的状态机
- **WHEN** a tool call is observed, resolved, executed, completed, and replayed
- **THEN** runtime SHALL expose an ordered observable transition sequence for those lifecycle steps instead of requiring callers to infer them only from the final transcript

### Requirement: Tool lifecycle events form a closed typed union
The runtime SHALL model observable tool lifecycle events as a closed typed union with distinct variants for envelope observation, resolution start, resolution completion, execution queueing, execution start, progress emission, terminal outcome recording, and replay commit.

#### Scenario: progress 事件不冒充 terminal lifecycle
- **WHEN** a tool emits progress while still executing
- **THEN** runtime SHALL expose that as a progress lifecycle event variant and SHALL NOT treat it as terminal outcome recording or replay commit

### Requirement: Tool lifecycle state progresses monotonically
The runtime SHALL ensure that the observable lifecycle state projected from tool lifecycle events progresses monotonically from observation toward replay, without skipping required predecessor transitions or re-entering execution after a non-executable resolution.

#### Scenario: execution_started 不能早于 executable resolution
- **WHEN** a tool call enters execution
- **THEN** runtime SHALL have already emitted a resolution-completed lifecycle event indicating that the call resolved as executable

#### Scenario: denied 或 invalid call 不进入 running
- **WHEN** a tool call resolves as denied or invalid
- **THEN** runtime SHALL NOT emit an execution-started lifecycle event for that call and SHALL instead proceed through a terminal outcome record suitable for replay

#### Scenario: replay_committed 不能跳过 terminal outcome
- **WHEN** a tool result is committed into ordered continuation history
- **THEN** runtime SHALL already have recorded a terminal `ToolOutcome` for that same call before emitting replay-committed lifecycle observation

### Requirement: Tool lifecycle events are surfaced as first-class turn events
The runtime SHALL surface tool lifecycle observations through the turn event stream as first-class typed events, so session controllers and hosts can consume them without scraping transcript messages or unstructured metadata.

#### Scenario: host 通过 turn event 直接消费 tool lifecycle
- **WHEN** a host adapter observes a turn that includes tool resolution, execution, and replay
- **THEN** the runtime SHALL make those tool lifecycle observations available through typed turn events rather than requiring the host to reconstruct them from emitted transcript messages

### Requirement: Catalog and state capabilities are scoped and policy-aware
The runtime SHALL ensure that catalog views, app state, file state, and memory access exposed to tools respect the active execution policy, namespace boundaries, and guarded resource constraints.

#### Scenario: tool catalog 反映当前 execution policy ceiling
- **WHEN** a tool inspects the currently available tools during a turn
- **THEN** the exposed `tool_catalog` SHALL reflect the effective tool pool allowed by the current execution policy rather than the unrestricted global registry

#### Scenario: app_state 与 file_state 避免无界共享
- **WHEN** multiple tools interact with runtime state or file-observation state during the same session
- **THEN** runtime SHALL expose namespaced `app_state` and policy-aware `file_state` handles rather than an unbounded shared metadata dictionary

#### Scenario: file_state 暴露 conflict key 与 guarded 状态
- **WHEN** a tool needs to reason about file conflicts or whether a path is guarded or reserved
- **THEN** runtime SHALL expose conflict-key and guarded-path information through `file_state` rather than requiring the tool to inspect internal runtime services

### Requirement: Legacy tool definitions remain executable through a compatibility adapter
The runtime SHALL provide a compatibility path that maps legacy schema-and-trait based tool definitions onto the richer capability contract without requiring existing tools to be rewritten immediately.

#### Scenario: 现有工具只声明静态 traits
- **WHEN** 某个现有 tool definition 只声明静态 `traits`、`validate_input`、`check_permissions` 和 `execute`
- **THEN** runtime SHALL 仍能执行该工具，并 SHALL 使用兼容适配规则推导默认 execution semantics

