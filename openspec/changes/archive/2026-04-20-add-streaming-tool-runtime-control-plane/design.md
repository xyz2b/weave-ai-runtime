## Context

当前 Python runtime 已经有 `ToolDefinition`、`ToolContext`、`ToolScheduler` 和共享 permission / hook / host bridge 控制面，但工具执行链路仍然是：

1. model stream 结束并提交完整 assistant message
2. 从 message 中抽取全部 `tool_use`
3. 使用 batch scheduler 执行 tools
4. 将 `tool_result` 统一回填为下一轮 continuation

这个模型能支持基础工具调用，但还没有进入参考实现那种“tool 是 runtime-managed capability，`tool_use` block 一出现就可进入调度器”的运行方式。当前主要缺口有四类：

- 工具契约仍偏静态，`traits` 无法表达输入相关并发语义、fatal failure policy、host-facing render/classifier metadata 等运行语义。
- tool orchestration 是 post-message batch 模式，没有 provider-agnostic 的 capability 分层、没有 early start，也没有稳定的 ordered replay buffer。
- sibling failure 语义不足，尤其 `bash` 一类工具的失败状态没有稳定映射到 orchestration policy。
- progress 与 capability refresh 虽已有局部 API 槽位，但没有真正接入 turn event stream 和 execution policy state。

## Goals / Non-Goals

**Goals:**

- 让工具定义从“可执行 schema + traits”升级为“包含运行语义的 capability contract”。
- 让 `ToolDefinition` 形成稳定的两阶段工具契约：定义期的 `ToolExecutionSemantics` 与调用期的 `ResolvedToolExecutionSemantics`。
- 在 `TurnEngine` 下引入 streaming tool orchestration，使工具能够在 streamed `tool_use` 成形后尽早执行。
- 让 `StreamingToolExecutor` 成为 provider-agnostic 的能力分层组件，而不是默认假设所有模型都具备参考实现风格 block streaming。
- 将并发、安全性和 failure cascade 的判定建立在规范化输入和工具语义上，而不是仅靠静态布尔值。
- 打通 tool progress、tool result ordering 和 capability refresh 到 shared control plane 与 host bridge。
- 将 `ToolContext` 从 service bag 提升为显式 capability container，并把标准 capability 从 `metadata` / `runtime_services` 中拆出来。
- 在不要求一次性重写所有 existing tools 的前提下，保留兼容路径并增加 conformance coverage。

**Non-Goals:**

- 不在这个 change 中重做整个 turn engine 或 query message protocol。
- 不要求第一版完整复刻参考实现所有 UI 呈现细节或产品专用 classifier 流程。
- 不在这个 change 中引入新的外部调度依赖或完整 plugin / MCP 发现系统。
- 不强制所有 builtin / user tools 立刻迁移到全新的定义格式，只要求提供兼容适配层。

## Decisions

### 1. 在 `ToolDefinition` 之上增加显式 execution semantics contract，并把调用期语义解析成稳定 snapshot

新的工具契约将保留现有 schema、validation、permission 和 execute 入口，但额外引入 `ToolExecutionSemantics`。它至少覆盖：

- `is_read_only(input, context)`
- `is_concurrency_safe(input, context)`
- `interrupt_behavior(input, context)`
- `failure_policy(input, context)`
- `render_tool_use_message(input, context)`
- `render_tool_result_summary(result, input, context)`
- `to_classifier_input(input, context)`

但 runtime 不应在一轮调用中到处零散地重复调用这些方法。更合理的执行模型是：

1. schema normalization
2. tool-local validation
3. pre-tool hook input rewriting
4. permission / approval 阶段可能产生的 `updatedInput`
5. 基于最终 execution-bound input 求值 `ToolExecutionSemantics`
6. 生成单一的 `ResolvedToolExecutionSemantics`
7. 调度器、权限日志、host UI、classifier、tool result mapping 共享这份 resolved snapshot

推荐的结构是：

```text
ToolDefinition
  - identity/schema/validator/permission/executor
  - semantics: ToolExecutionSemantics

ToolExecutionSemantics
  - per-call resolvers

ResolvedToolExecutionSemantics
  - read_only: bool
  - concurrency_safe: bool
  - interrupt_behavior: InterruptBehavior
  - failure_policy: ToolFailurePolicy
  - tool_use_presentation: ToolUsePresentation | None
  - tool_result_summary: ToolResultSummary | None
  - classifier_input: ToolClassifierInput | None
```

其中建议优先固定的子模型如下：

```text
ToolFailurePolicy
  - failure_mode: "report_only" | "error_result" | "fatal"
  - result_classifier: "exception_only" | "nonzero_exit_or_exception" | "custom"
  - cancel_running_siblings: bool
  - block_queued_siblings: bool
  - abort_model_stream: bool
  - surfaced_status: ToolCallStatus

ToolUsePresentation
  - title: str
  - subtitle: str | None
  - icon_hint: str | None
  - emphasis: "low" | "normal" | "high"

ToolResultSummary
  - title: str
  - summary: str
  - status: "success" | "denied" | "cancelled" | "error"
  - detail_lines: tuple[str, ...]

ToolClassifierInput
  - operation: str
  - summary: str
  - target_paths: tuple[str, ...]
  - target_urls: tuple[str, ...]
  - risk_level: "read" | "write" | "exec" | "network" | "delegate"
  - side_effects: bool
  - tags: tuple[str, ...]
```

这里的关键点不是字段名字本身，而是：

- `ToolFailurePolicy` 必须同时覆盖“如何把结果判成失败”和“失败后如何影响 siblings / model stream”。
- `ToolClassifierInput` 必须是结构化对象，而不是一段随意拼接字符串；否则自动分类会重新走向 ad-hoc prompt engineering。
- `ToolUsePresentation` / `ToolResultSummary` 必须共享同一份 resolved semantics，避免 UI 和 scheduler 各自再推导一次。

Why:

- 现有 `ToolTraits` 只能表达静态布尔语义，无法覆盖“同一个工具在不同输入下并发安全性不同”的场景。
- execution semantics 是 orchestration、host UI、自动分类和权限共享的 runtime 语义，应该在工具契约层统一建模。
- 若不引入 resolved snapshot，同一 tool call 的 scheduler、UI 和 permission/logging 可能基于不同输入时刻得到不一致结论。
- 通过 compatibility adapter 可以让现有基于 `traits` 的工具继续工作，不需要一次性重写。

Alternatives considered:

- 继续沿用静态 `traits`，只在 scheduler 中增加针对单个工具的特殊判断。拒绝，因为这会把运行语义散落到 orchestrator 和 builtin 代码里。
- 将 `is_read_only`、`interrupt_behavior` 等在运行期按需随处调用。拒绝，因为这会导致同一调用在不同子系统里出现重复求值和不一致结果。
- 直接替换掉现有 `ToolDefinition`。拒绝，因为这会造成过高的迁移成本，也会让当前 builtin / discovery 立即失效。

### 2. 将 `ToolContext` 改造为显式 capability container，并隐藏原始 `runtime_services`

当前 `ToolContext` 已经很重，但大量能力仍以宽泛字段或内部 service bag 形式暴露，这会导致工具通过 `runtime_services` 或 `metadata` 访问本不该依赖的内部结构。新的 `ToolContext` 应改为显式 capability container，至少包含：

- `tool_catalog`
- `agent_catalog`
- `skill_catalog`
- `permission_context`
- `query_context`
- `app_state`
- `file_state`
- `progress`
- `notifications`
- `refresh_capabilities`
- `memory_access`

这些字段都应是窄接口，而不是直接把 registry、host、memory manager 或 runtime services 原样泄露给 tool。

建议的职责拆分如下：

```text
tool_catalog / agent_catalog / skill_catalog
  - read-only catalog views
  - reflect current execution-policy ceiling
  - support lookup/list/snapshot metadata, not raw mutation

permission_context
  - resolved permission ceiling and applicable rules
  - read-only to tools

query_context
  - session_id / turn_id / agent_name / cwd
  - current message snapshot
  - selected executor tier
  - normalized model capability profile
  - abort handle / continuation metadata

app_state
  - namespaced runtime key-value state
  - turn/session scoped get/set/compare-and-set

file_state
  - file snapshots, digests, read/write observations
  - conflict keys for orchestration
  - reserved/guarded path visibility

progress
  - emit start/update/complete progress events

notifications
  - emit user-visible runtime notifications

refresh_capabilities
  - request capability refresh with explicit scope/reason
  - writes back into shared control plane

memory_access
  - controlled memory read/write surface
  - respects guarded roots and agent memory policy
```

建议优先固定的 capability 形状如下：

```text
QueryContext
  - session_id: str
  - turn_id: str
  - agent_name: str
  - cwd: Path
  - messages: tuple[RuntimeMessage, ...]
  - selected_executor_tier: "full_streaming" | "buffered" | "batch" | "none"
  - model_capabilities: NormalizedModelCapabilities
  - abort_handle: QueryAbortHandle
  - continuation_metadata: Mapping[str, Any]

AppState
  - get(namespace: str, key: str) -> Any | None
  - set(namespace: str, key: str, value: Any) -> None
  - compare_and_set(namespace: str, key: str, expected: Any, value: Any) -> bool

FileState
  - stat(path: str) -> FileSnapshot | None
  - read_observed(path: str) -> FileObservation | None
  - record_read(path: str, digest: str | None = None) -> None
  - record_write_intent(path: str) -> FileConflictHandle
  - conflict_key(path: str) -> str
  - guarded_status(path: str) -> "allowed" | "guarded" | "reserved"

ProgressHandle
  - start(label: str, metadata: Mapping[str, Any] | None = None) -> str
  - update(progress_id: str, message: str, percent: float | None = None) -> None
  - complete(progress_id: str, message: str | None = None) -> None

NotificationsHandle
  - emit(message: str, level: str = "info") -> None

CapabilityRefreshHandle
  - request(scope: "tool_pool" | "skill_pool" | "policy", reason: str) -> RefreshReceipt

MemoryAccess
  - read(scope: str, query: str | None = None) -> Sequence[MemoryEntry]
  - append(scope: str, entry: MemoryEntry) -> None
```

尤其是 `FileState`，它不应只是“文件缓存”。它还有三个 runtime 角色：

- 为工具和 orchestrator 提供稳定的 conflict key
- 记录 read/write observation，支撑 stale-read 检测
- 暴露 guarded/reserved path 状态，避免 tools 自己猜哪些路径不能碰

`QueryContext` 则承担“这次调用发生在什么运行时环境里”的最小完备描述。它不应该再要求工具去顶层字段和 `metadata` 里拼装 session / turn / cwd / executor / capability 信息。

catalog 与 permission 侧也建议固定成如下窄接口：

```text
CatalogEntryView
  - name: str
  - aliases: tuple[str, ...]
  - description: str
  - source_label: str | None
  - metadata: Mapping[str, Any]

ToolCatalog
  - get(name_or_alias: str) -> CatalogEntryView | None
  - list() -> Sequence[CatalogEntryView]
  - resolve_alias(name_or_alias: str) -> str | None
  - snapshot() -> Sequence[CatalogEntryView]

AgentCatalog
  - get(name: str) -> CatalogEntryView | None
  - list() -> Sequence[CatalogEntryView]
  - snapshot() -> Sequence[CatalogEntryView]

SkillCatalog
  - get(name: str) -> CatalogEntryView | None
  - list() -> Sequence[CatalogEntryView]
  - snapshot() -> Sequence[CatalogEntryView]

PermissionContextView
  - effective_mode: PermissionMode
  - interactive_prompts_allowed: bool
  - bubbles_to_caller: bool
  - requires_host_mediation: bool
  - rules: tuple[PermissionRuleView, ...]

PermissionRuleView
  - target_type: str
  - selector: str
  - behavior: "allow" | "ask" | "deny"
  - message: str | None
  - source: str | None
```

这里有几个边界需要刻意保持：

- `tool_catalog` / `agent_catalog` / `skill_catalog` 是当前 execution policy 下的只读可见视图，不是全局 registry 代理。
- `resolve_alias()` 属于 catalog capability，而不是让工具自己碰全局 registry 做名字推断。
- `permission_context` 是“当前有效权限环境的可读快照”，不是发起审批或直接放行的接口。
- tools 可以根据 `interactive_prompts_allowed`、`bubbles_to_caller` 等信号调整行为，但不能据此自判“这次已经获批”。
- 真正的授权决策仍然只能由 runtime permission engine 在执行路径上完成。

`query_context` 应吸收当前散落在 `ToolContext` 顶层的 `session_id`、`turn_id`、`agent_name`、`cwd`、`messages`、`abort_signal` 等基础字段。`metadata` 可以保留给 runtime 内部兼容，但标准 tool capability 不能再要求从 `metadata` 中猜测获取。

Why:

- tools 看到的应是 capability，而不是 runtime 内部装配细节。
- 显式 capability 能让权限、隔离、测试和文档边界稳定下来。
- `runtime_services` 继续外泄，会让工具绕过 policy ceiling、host bridge 和 memory guard rails。
- 将 `app_state` 与 `file_state` 独立出来，才能支持 file-aware orchestration、staleness detection 和 namespaced runtime state，而不是继续把这些信息塞进 `metadata`。

Alternatives considered:

- 保留当前 `ToolContext` 结构，只是继续往里加字段。拒绝，因为这会让 context 继续膨胀，但边界仍然不清晰。
- 直接把 `RuntimeServices` 暴露给 tools，并通过约定限制用法。拒绝，因为约定无法替代 capability boundary。
- 让每个 tool 自行注入所需 helper。拒绝，因为这会让 builtin 和 user tools 的能力模型分裂。

### 3. 将工具调用生命周期收敛为显式对象模型参考实现已经隐含存在工具调用生命周期，但状态分散在 streamed tool queue、tool execution pipeline、context modifier 和 tool result message 之间。为了让这个 runtime 更适合作为 framework，我们应将生命周期对象显式化为：

```text
ToolCallEnvelope
  - envelope_id: str
  - tool_use_id: str
  - sequence_index: int
  - raw_tool_name: str
  - raw_input: Mapping[str, Any]
  - assistant_message_id: str
  - provider_request_id: str | None
  - block_index: int | None
  - observed_at: datetime
  - query_snapshot: QueryContext

ResolvedPermissionDecision
  - variant: PermissionAllowed | PermissionDenied

PermissionAllowed
  - kind: "allow"
  - source: "rule" | "classifier" | "hook" | "prompt" | "host" | "mode" | "policy"
  - updated_input: Mapping[str, Any] | None
  - user_modified: bool
  - accept_feedback: str | None
  - content_blocks: tuple[Any, ...]
  - audit_metadata: Mapping[str, Any]

PermissionDenied
  - kind: "deny"
  - source: "rule" | "classifier" | "hook" | "prompt" | "host" | "mode" | "policy"
  - denied_status: "denied" | "cancelled"
  - message: str
  - content_blocks: tuple[Any, ...]
  - retry_hint: "none" | "retryable"
  - audit_metadata: Mapping[str, Any]

ToolCapabilityContext
  - tool_use_id: str
  - canonical_tool_name: str | None
  - assistant_message_id: str
  - replay_index: int
  - executor_tier: "full_streaming" | "buffered" | "batch" | "none"
  - query_context: QueryContext
  - tool_catalog: ToolCatalog
  - agent_catalog: AgentCatalog
  - skill_catalog: SkillCatalog
  - permission_context: PermissionContextView
  - app_state: AppState
  - file_state: FileState
  - progress: ProgressHandle
  - notifications: NotificationsHandle
  - refresh_capabilities: CapabilityRefreshHandle
  - memory_access: MemoryAccess

ResolvedToolCall
  - envelope: ToolCallEnvelope
  - resolution_status: "executable" | "denied" | "invalid"
  - canonical_tool_name: str | None
  - tool_definition_ref: ToolDefinition | None
  - execution_input: Mapping[str, Any] | None
  - observable_input: Mapping[str, Any] | None
  - resolved_semantics: ResolvedToolExecutionSemantics | None
  - permission_decision: ResolvedPermissionDecision | None
  - scheduler_lane: ToolSchedulerLane | None
  - replay_index: int
  - capability_context: ToolCapabilityContext

ToolSchedulerLane
  - lane_kind: "concurrent" | "exclusive" | "conflict"
  - lane_key: str | None
  - conflict_domains: tuple[str, ...]
  - failure_scope_key: str
  - shares_concurrency: bool
  - derivation_mode: "precise" | "coarse"

ContextUpdate
  - variant: AppStateSet | FileObservationRecorded | MemoryAppended | CapabilityRefreshRequested | NotificationEmitted | TranscriptAttachmentAdded | LegacyContextModifierWrapped

AppStateSet
  - kind: "app_state_set"
  - apply_phase: "before_replay" | "after_replay"
  - namespace: str
  - key: str
  - value: Any

FileObservationRecorded
  - kind: "file_observation_recorded"
  - apply_phase: "before_replay"
  - observation_kind: "read" | "write_intent" | "write_commit"
  - path: str
  - digest: str | None
  - conflict_key: str | None

MemoryAppended
  - kind: "memory_appended"
  - apply_phase: "after_replay"
  - scope: str
  - entry: MemoryEntry

CapabilityRefreshRequested
  - kind: "capability_refresh_requested"
  - apply_phase: "before_replay"
  - scope: "tool_pool" | "skill_pool" | "policy"
  - reason: str

NotificationEmitted
  - kind: "notification_emitted"
  - apply_phase: "before_replay" | "with_replay" | "after_replay"
  - level: "info" | "warning" | "error"
  - message: str

TranscriptAttachmentAdded
  - kind: "transcript_attachment_added"
  - apply_phase: "with_replay"
  - attachment_type: str
  - payload: Mapping[str, Any]

LegacyContextModifierWrapped
  - kind: "legacy_context_modifier_wrapped"
  - apply_phase: "after_replay"
  - adapter_label: str
  - summary: str

ToolOutcome
  - resolved_call: ResolvedToolCall
  - status: ToolCallStatus
  - terminal_reason: str | None
  - raw_output: Any | None
  - error_message: str | None
  - result_block: ToolResultBlockParam | equivalent
  - result_summary: ToolResultSummary | None
  - context_updates: tuple[ContextUpdate, ...]
  - completion_index: int
  - replay_index: int
  - replay_eligible: bool
```

这三层各自承担的职责应明确区分：

- `ToolCallEnvelope`：描述“模型刚刚发出了什么 tool call”。它是原始的、不可变的、仍未绑定最终输入和调度语义的调用记录。
- `ResolvedToolCall`：描述“runtime 最终认定这次调用是什么”。它必须在所有 input-mutating 阶段稳定后生成，包括 validation、hooks、permission updatedInput、observable backfill 和 semantics resolution。正常路径下，lane assignment、capability view 与 replay ordering 都在这一层冻结；提前被 deny 或判为 invalid 的调用，也应该在这一层留下结构化 resolution record，而不是只剩一条错误消息。
- `ToolOutcome`：描述“这次工具调用最终发生了什么”。它是 replay buffer、host event stream、tool result mapping 和 transcript 持久化看到的终态对象。

这里建议再明确一条原则：生命周期对象本身应尽量不可变，状态转移靠事件表达，而不是在同一个 record 上持续打补丁。也就是说：

```text
ToolCallEnvelope --immutable-->
  ResolvedToolCall --immutable-->
    ToolOutcome

turn-scoped lifecycle events:
  envelope_observed
  resolution_started
  resolution_completed
  execution_queued
  execution_started
  progress_emitted
  outcome_recorded
  replay_committed
```

这样 host、tests 和 tracing 看的是同一条状态机，而不是各自猜控制流走到了哪一步。

建议把这组事件再收敛成 closed ADT，而不是“事件名 + 任意 metadata”：

```text
ToolLifecycleEvent
  - variant: EnvelopeObserved | ResolutionStarted | ResolutionCompleted | ExecutionQueued | ExecutionStarted | ProgressEmitted | OutcomeRecorded | ReplayCommitted

EnvelopeObserved
  - kind: "envelope_observed"
  - tool_use_id: str
  - replay_index: int
  - assistant_message_id: str
  - raw_tool_name: str

ResolutionStarted
  - kind: "resolution_started"
  - tool_use_id: str
  - replay_index: int

ResolutionCompleted
  - kind: "resolution_completed"
  - tool_use_id: str
  - replay_index: int
  - resolution_status: "executable" | "denied" | "invalid"
  - canonical_tool_name: str | None

ExecutionQueued
  - kind: "execution_queued"
  - tool_use_id: str
  - replay_index: int
  - lane_kind: "concurrent" | "exclusive" | "conflict"
  - lane_key: str | None

ExecutionStarted
  - kind: "execution_started"
  - tool_use_id: str
  - replay_index: int
  - lane_kind: "concurrent" | "exclusive" | "conflict"

ProgressEmitted
  - kind: "progress_emitted"
  - tool_use_id: str
  - replay_index: int
  - progress_id: str
  - message: str
  - percent: float | None

OutcomeRecorded
  - kind: "outcome_recorded"
  - tool_use_id: str
  - replay_index: int
  - completion_index: int
  - status: ToolCallStatus

ReplayCommitted
  - kind: "replay_committed"
  - tool_use_id: str
  - replay_index: int
  - completion_index: int
  - status: ToolCallStatus
```

这里有两个刻意的边界：

- `ProgressEmitted` 仍然属于 turn event stream，但不改变 terminal lifecycle state；它只是执行中事件。
- `ReplayCommitted` 不是 Outcome 的同义词。Outcome 代表“已经终态”；ReplayCommitted 代表“已经按顺序进入 continuation history”。两者必须分开，否则 ordered replay 的约束就会再次模糊。

建议再把可投影的状态枚举固定下来：

```text
ToolLifecycleStage
  - "observed"
  - "resolving"
  - "resolved_non_executable"
  - "queued"
  - "running"
  - "terminal_pending_replay"
  - "replayed"
```

它不是新的持久化主对象，而是 host、tests、tracing 基于 `ToolLifecycleEvent` 推导出来的单调状态投影。

推荐的状态转移表如下：

```text
observed
  -> resolving

resolving
  -> resolved_non_executable   (permission deny / validation error / unknown tool)
  -> queued                    (resolved executable call)

resolved_non_executable
  -> terminal_pending_replay   (synthetic denied/invalid outcome recorded)

queued
  -> running                   (executor actually starts)
  -> terminal_pending_replay   (cancelled before start / fatal sibling cancellation)

running
  -> running                   (progress only; no state change)
  -> terminal_pending_replay   (success / error / cancelled outcome recorded)

terminal_pending_replay
  -> replayed

replayed
  -> [terminal]
```

这张表里最关键的是三条禁止规则：

1. `execution_started` 不能先于 `resolution_completed(executable)` 出现。
2. `replay_committed` 不能先于 `outcome_recorded` 出现。
3. `resolved_non_executable` 不得再进入 `running`；它只能通过 synthetic terminal outcome 进入 replay。

也就是说，runtime 不应该允许“permission denied 但还是启动执行”或“tool result 已提交，但没有 terminal outcome record”这类时序短路。

`ResolvedPermissionDecision`、`ContextUpdate` 与 `ToolCapabilityContext` 需要再额外说明：

- `ResolvedPermissionDecision` 应直接固定成 closed ADT，而不是继续保留宽松 record。这里刻意只有 `PermissionAllowed` / `PermissionDenied` 两个 variant，没有 `ask`、`pending` 或其他中间态；因为一旦进入 `ResolvedToolCall`，permission mediation 就已经结束了。
- `PermissionAllowed` 可以带 `updated_input`，但真正的执行单一真值仍然是 `ResolvedToolCall.execution_input`。`updated_input` 留在 decision 上的目的主要是审计、调试和回放 host feedback，而不是让执行路径再做第二次输入归并。
- `PermissionDenied` 必须足够完整，能让 runtime 在不重新进入 permission engine 的前提下直接构造 denied/cancelled outcome。也就是说，`message`、`denied_status`、`content_blocks` 和 `retry_hint` 都应该是终态字段，而不是 host callback 的原始残片。
- `ToolCapabilityContext` 不应等同于“把整个 `ToolContext` 原样塞进 `ResolvedToolCall`”。更合理的做法是：它是基于 turn-scoped capability container 构造出的 call-scoped view，冻结 `query_context`、`tool_use_id`、`replay_index`、`executor_tier` 等调用元信息，但底层 `app_state` / `file_state` / `progress` / `memory_access` 仍然是能力句柄，而不是拍扁后的静态拷贝。
- `ContextUpdate` 同样应是 closed ADT，而不是 `update_kind + payload` 的松散袋子。它的价值不只是“类型更漂亮”，而是把 side effect 的 producer、phase 和 consumer 固定下来，让 replay、control plane 和 tests 能穷举处理。
- `ContextUpdate` 默认要求可序列化、可重放、可断言。任意闭包或 opaque callable 只能存在于 `LegacyContextModifierWrapped` 这个兼容 variant 里，而且只应作为过渡路径，而不是新实现的主路径。

建议把 `ContextUpdate.apply_phase` 的语义也固定死：

```text
before_replay
  - 可先于 terminal tool_result 提交
  - 适用于 capability refresh、file observation、部分 app_state 写入

with_replay
  - 必须和当前 replay slot 一起提交
  - 适用于 transcript attachment、需要与 tool_result 对齐的 host-visible side effect

after_replay
  - 只在 replay commit 成功后执行
  - 适用于 memory append、legacy context modifier、会影响长期状态的一次性写入
```

各 variant 的推荐用途也应尽量明确：

- `AppStateSet`：轻量 session/turn state 变更。若会影响当前 replay 之前的调度或后续 request 组装，可用 `before_replay`；否则优先 `after_replay`。
- `FileObservationRecorded`：记录 read/write observation 与 conflict domain 信息，通常在 replay 前就该生效，因为调度器和 stale-read 检测要消费它。
- `CapabilityRefreshRequested`：控制面事件，不应等待 transcript 顺序，因此默认 `before_replay`。
- `TranscriptAttachmentAdded`：这是 structured output、hook summary 或 permission feedback 与 tool result 对齐的标准形式，因此强制 `with_replay`。
- `MemoryAppended`：默认 `after_replay`，避免结果尚未真正提交就污染长期 memory。
- `LegacyContextModifierWrapped`：仅用于兼容旧工具返回的闭包式 context modifier，并要求带上 adapter label 与摘要，方便后续逐步清退。
- progress 更新刻意不放进 `ContextUpdate`。它属于 execution-time event stream，而不是 terminal outcome side effect。

建议的生命周期主线如下：

```text
parseable tool_use observed
  -> ToolCallEnvelope(replay_index frozen)
  -> resolution_started
  -> normalize / validate / pre-tool hooks / permission mediation
  -> resolve semantics from final execution-bound input
  -> derive scheduler lane from semantics + conflict domains
  -> freeze ToolCapabilityContext
  -> ResolvedToolCall
  -> queued / running / terminal
  -> ToolOutcome(completion_index assigned)
  -> replay buffer checks contiguous replay window
  -> ordered replay by replay_index
```

其中 replay 和 completion 要明确区分：

- `replay_index` 是“模型原始看见的 tool_use 顺序”，在 envelope 阶段就固定。
- `completion_index` 是“runtime 实际完成顺序”，只有在 terminal outcome 产生时才分配。
- replay buffer 只允许按 `replay_index` 提交连续窗口；`completion_index` 只用于调试、指标和 race 分析，不参与 transcript 排序。
- progress、lifecycle events 和 notifications 可以绕过 replay buffer 立即发出；真正进入 continuation history 的 terminal `tool_result` 必须服从 replay 顺序。

对照参考实现，这一层并不是没有，而是没有被显式建模成统一对象：

- `ToolCallEnvelope` 的隐式对应物大致是 `StreamingToolExecutor` 中刚入队的 `TrackedTool` 加 streamed `tool_use` block。
- `ResolvedToolCall` 的隐式对应物分散在 `runToolUse()` / `checkPermissionsAndCallTool()` 内部，从 `parsedInput`、`processedInput`、hook rewrites、`permissionDecision.updatedInput` 一路收敛到真正传给 `tool.call()` 的 `callInput`。
- `ToolOutcome` 的隐式对应物则是最终生成的 `tool_result` message、附带的 attachment/progress、以及 `contextModifier`。

所以结论不是“参考实现没有生命周期”，而是“参考实现有真实生命周期，但它主要存在于控制流和局部变量里，而不是 framework 友好的领域对象里”。

Why:

- 这可以把当前分散在 executor、permission、tool result mapping 里的阶段状态收束成稳定边界。
- `ResolvedToolCall` 是 resolved semantics、capability container 和 scheduler lane 的自然汇合点。
- `ToolOutcome` 让 ordered replay、host observation 和 transcript persistence 共享统一的终态对象，而不是各自拼装结果。

Alternatives considered:

- 继续只用临时局部变量和 queue item 跟踪工具执行。拒绝，因为这会让生命周期语义继续隐含在控制流里，难以测试和扩展。
- 在 `ToolResult` 上继续堆字段来表达全部阶段。拒绝，因为 `ToolResult` 只适合表达工具函数返回值，不适合承载完整调用生命周期。

### 4. 新增 `StreamingToolOrchestrator`，把 tool execution 从 post-message batch 模式移到 stream-aware 模式

`StreamingToolOrchestrator` 将作为 `TurnEngine` 的子组件，消费流式模型输出中已经完成的 `tool_use` blocks。它负责：

- 在 block 成形后立即登记 tool slot
- 在满足启动条件时尽早执行 eligible tools
- 维护原始 `tool_use` 顺序索引
- 缓存完成结果，直到可以按稳定顺序回放为 `tool_result`

Why:

- 参考实现风格的 tool runtime 关键不是“并行执行”本身，而是“在流中调度，然后按稳定顺序回放”。
- ordered replay buffer 和 execution lanes 都是 orchestration 关注点，不应继续耦合在 `TurnEngine` 的 post-processing 代码中。
- 独立组件更便于 golden tests 和 host event instrumentation。

Alternatives considered:

- 保留现有 `ToolScheduler`，在 `message_stop` 后继续批量跑。拒绝，因为这无法满足 early start，也无法表达流中 sibling cancellation。
- 把 orchestration 下沉到 model client。拒绝，因为工具运行语义属于 runtime，不属于 provider transport。

### 5. `StreamingToolExecutor` 采用 capability tier 设计，并按 provider 实际能力自动降级

runtime 不会按 “参考实现 / ChatGPT / DeepSeek / Qwen” 这种 provider 名称选择工具执行器，而是按 adapter 归一化后的 model capabilities 选择最高可行 tier。我们定义三层执行器：

- `FullStreamingToolExecutor`
  - 需要结构化 tool calls
  - 需要 tool call finalize boundary，能够判断某个 `tool_use` 已完整可执行
  - 支持在 `message_stop` 前 early start
- `BufferedToolExecutor`
  - 需要结构化 tool calls
  - 不要求在流中拿到可安全启动的 finalize boundary
  - 等到 message 完成或 provider 给出完整 tool call 后再执行，但仍保留统一的 ordered replay / failure policy
- `BatchToolExecutor`
  - 只要求 provider 能在完整响应结束后给出可解析的 tool calls
  - 无 early start，退化为 batch tool loop

selector 会根据 model adapter 暴露的 capability profile 决定本轮使用的 executor。若 adapter 没法满足更高 tier 要求，就自动降级到更低 tier；若运行期观测到 promised capability 缺失或不稳定，也允许从 `FullStreaming` 回落到 `Buffered`，或从 `Buffered` 回落到 `Batch`，但必须保留显式 mode 信息供日志、host 和测试观察。

若 provider 连“完整响应后给出可解析 tool calls”这一最低条件都不满足，则本轮不选择任何 tool executor，并按 fail-closed 方式把该 provider 视为当前 turn 不支持 tools。

建议的 capability profile 至少包括：

- `structured_tool_calls`
- `streaming_tool_call_deltas`
- `tool_call_finalize_boundary`
- `multiple_tool_calls_per_message`
- `abort_signal_passthrough`

Why:

- 框架目标是 provider-agnostic runtime，不能把参考实现的 block protocol 当成硬前提。
- 三层模型能让高能力 provider 获得 early start 收益，同时让其他 provider 复用同一套 tool runtime 语义。
- capability-based selection 比 provider name branching 更稳定，也更适合作为 OpenAI、DeepSeek、Qwen 等 adapter 的统一契约。

Alternatives considered:

- 只实现参考实现风格 full streaming executor。拒绝，因为这会直接把 runtime 绑死在少数 provider 的协议能力上。
- 对所有 provider 一律走 batch。拒绝，因为这会放弃高能力 provider 上已经可获得的早启动与并发收益。

### 6. 并发策略基于“规范化输入后的 execution semantics”，并通过 lane 模型执行

工具在进入调度前会先完成：

- input schema normalization
- tool-local validation
- pre-tool hook input rewriting

随后 runtime 根据最终 execution-bound input 求值得到 execution semantics，并据此将 `ResolvedToolCall` 放入：

- 可并发 lane
- 串行 mutating lane
- 受 conflict key 或 fatal policy 影响的特殊 lane

建议把 lane derivation 进一步固定成“能精确就精确，达不到就保守降级”：

1. 若 `resolution_status != "executable"`，则不分配 execution lane，只保留 replay slot。
2. 若 `resolved_semantics.concurrency_safe == false`，则直接进入 `exclusive` lane。
3. 若工具可并发，则优先使用 `resolved_semantics.classifier_input.target_paths`、tool-local scheduler hints，或其他结构化 target 信息，经由 `file_state.conflict_key()` 归一化出 `conflict_domains`。
4. 若得到空 conflict domain 且 `read_only == true`，则进入共享 `concurrent` lane。
5. 若得到明确 conflict domain，则进入 `conflict` lane，仅与 domain 不冲突的调用并行。
6. 若 runtime 无法可靠推出 conflict domain，则自动降级到更保守的 `exclusive` lane，而不是乐观并发。

这条规则非常重要，因为它把“自动降级”从 executor tier 扩展到了 scheduler precision 本身。provider 能力不足时降级 executor；tool target 信息不足时降级 lane 精度。

Why:

- 并发安全与否本质上是工具语义，而不是调用栈位置。
- lane 模型既能保留简单场景下的并行读，又能支持未来更细粒度的 conflict domain。
- 在 hooks 之后再分类，能避免对已被 hook 改写的输入做错误判定。

Alternatives considered:

- 继续用 `read_only && concurrency_safe` 的静态分批逻辑。拒绝，因为这正是当前偏离参考实现设计的核心限制。
- 将并发判定推迟到工具内部。拒绝，因为那会让 runtime 失去统一编排能力。

### 7. 用 result ordering buffer 和 failure policy 统一处理 replay 与 sibling cancellation

每个 `ToolCallEnvelope` 在被观测到时都会获得稳定顺序号，并在 `ResolvedToolCall` 中冻结为 `replay_index`。工具可以乱序完成，但 replay buffer 只消费 `ToolOutcome`，并且只有当前面所有已知 `replay_index` 都可提交时，runtime 才会把对应 `tool_result` 写入 continuation history。与此同时，runtime 还会维护 failure policy：

- non-fatal failure 只影响当前调用
- fatal failure 可以取消正在运行或尚未启动的 sibling calls
- cancellation / denied / error 会以显式状态回填到 tool results 和 host events

建议把 replay eligibility 规则也写死，不要留给实现阶段“差不多”处理：

- 一个 `ToolOutcome` 只有在自己已经 terminal，且所有更小的 `replay_index` 都已有 terminal outcome 时，才是 `replay_eligible = true`。
- `denied`、`cancelled`、`invalid` 或 streaming fallback 产生的 synthetic terminal outcome 也必须占住原始 replay slot，不能被跳过。
- replay commit 必须按 `replay_index` 升序批量推进；即便某个 outcome 更早完成，它也只能等待前面的 slot 补齐。
- `context_updates` 需要带 `apply_phase`。例如 capability refresh / notifications 往往可以 `before_replay` 发出；而 transcript attachment 或 terminal tool_result summary 应和 replay 一起提交。
- fatal sibling cancellation 不能只中断运行中的调用，还必须为被阻塞或被丢弃的调用生成明确 outcome，这样 replay buffer 才不会卡住。

Why:

- ordered replay 是参考实现风格 streaming tool execution 的关键稳定性保证。
- fatal failure cascade 必须是 runtime policy，而不是依赖工具自己随意抛异常。
- 明确状态有助于 host 呈现、后续模型 continuation 和 golden tests。

Alternatives considered:

- 使用完成顺序直接回填。拒绝，因为这会破坏模型看到的 tool result 稳定顺序。
- 只要有错误就终止整个 turn。拒绝，因为这会丢失对 sibling cancellation 与 partial completion 的细粒度表达。

### 8. progress 和 capability refresh 统一走 control plane，而不是停留在 tool-local callback

tool progress 会作为 turn-scoped event 经由 host bridge 向外发出。tool-triggered capability refresh 会写回 shared execution policy / tool catalog state，从而影响后续的 tool resolution 和下一次 provider request，而不只是修改当前 `ToolContext` 的局部缓存。

Why:

- progress 如果只存在于 `ToolContext`，host 无法稳定消费，也难以被测试。
- capability refresh 的意义在于改变后续能力可见性，因此必须进入 shared policy state。
- 这两类信号本质上都是 control plane 事件，不应继续做成 ad-hoc callback。

Alternatives considered:

- 维持当前 `progress_sink` / `refresh_tools()` 局部接口。拒绝，因为它们现在没有稳定接入 turn stream 和 policy propagation。
- 让工具直接操作 registry 或 host。拒绝，因为这会绕开 permission / policy / isolation 约束。

### 9. 按当前代码库固定模块边界，避免继续把语义堆回 `tool_runtime.py`

上面的对象和事件模型如果没有落到具体模块 ownership，上线时很容易重新退化成两个坏结果：

- 把 `ResolvedToolCall`、lane、replay、permission 收敛逻辑继续塞进 [tool_runtime.py](/Users/xyzjiao/AIProject/AIAgentRuntime/src/runtime/tool_runtime.py)
- 或者把 stream observation、orchestration、host event emission 全挤进 [turn_engine/engine.py](/Users/xyzjiao/AIProject/AIAgentRuntime/src/runtime/turn_engine/engine.py)

更稳妥的做法是沿着当前代码库已有边界增量拆分，而不是一次性重写目录结构。建议的 ownership 如下：

```text
definitions.py
  - author-time definitions only
  - ToolDefinition / ToolExecutionSemantics / ResolvedToolExecutionSemantics
  - presentation / classifier / failure-policy payload types
  - no call-scoped lifecycle objects

permissions/models.py + permissions/engine.py
  - raw permission request / rule / host outcome / policy evaluation
  - no ResolvedToolCall or replay semantics

tool_lifecycle.py            [new]
  - ToolCallEnvelope
  - ResolvedPermissionDecision
  - ToolCapabilityContext
  - ResolvedToolCall
  - ToolSchedulerLane
  - ContextUpdate
  - ToolOutcome
  - ToolLifecycleEvent
  - lifecycle-stage projection helpers

tool_resolution.py           [new]
  - normalize / validate / hook mediation / permission mediation
  - semantics resolution from final execution-bound input
  - build ResolvedToolCall
  - no queueing, replay, or host emission

tool_orchestration.py        [new]
  - StreamingToolOrchestrator
  - lane assignment
  - replay buffer
  - sibling failure cascade
  - lifecycle event emission order
  - no schema validation or hook execution internals

tool_executors.py            [new]
  - capability selector
  - FullStreamingToolExecutor / BufferedToolExecutor / BatchToolExecutor
  - provider-tier downgrade rules
  - feeds parseable tool observations into orchestrator

tool_runtime.py
  - keep as compatibility facade
  - ToolContext compat adapter and legacy scheduler bridge
  - thin execute-call helpers reused by orchestrator
  - should stop being the place where new orchestration state lives

turn_engine/models.py
  - normalized model capability profile
  - TurnStreamEvent additions for tool lifecycle emission
  - no tool resolution pipeline logic

turn_engine/engine.py
  - model streaming loop and attempt assembly
  - instantiate selected tool executor tier
  - route tool lifecycle events into turn event stream
  - translate replayed ToolOutcome into continuation messages
  - should not own lane/replay policy logic directly

session_runtime/controller.py
  - relay turn events to host and transcript
  - no tool lifecycle reconstruction

hosts/base.py
  - host transport contract only
  - receives typed turn events, including tool lifecycle events
  - should not infer lifecycle stage by scraping transcript/messages

builtins/tools.py + builtins/tool_impls.py
  - builtin tool semantics opt-in
  - no orchestration special cases beyond tool-local semantics
```

这套切分里最重要的几个判断是：

- `ResolvedPermissionDecision` 放在 `tool_lifecycle.py`，而不是 `permissions/models.py`。原因是它不是原始 permission engine 输出，而是“permission mediation 结束后，供 tool runtime/replay/host 使用的 call-scoped terminal projection”。
- `ToolLifecycleEvent` 放在 tool runtime 领域，而不是 host 层。host 只是消费 typed event，不应该定义 runtime 内部状态机。
- `turn_engine/engine.py` 负责“观察并转发”，不负责“解释并裁决”。一旦它自己开始做 lane 和 replay policy，后面就会再次长成一个大一统 mega-engine。
- `tool_runtime.py` 需要保留 compat facade，避免一次性把所有 import 路径和现有调用方打碎；但它不应继续增长为新的系统底座。

建议的调用主线如下：

```text
turn_engine.engine
  -> tool_executors.select_executor(...)
  -> selected executor observes parseable tool_use boundary
  -> tool_orchestration.observe_tool_use(...)
  -> ToolCallEnvelope allocated
  -> tool_resolution.resolve_tool_call(...)
  -> ResolvedToolCall returned
  -> tool_orchestration schedules / replays / emits lifecycle events
  -> turn_engine.engine wraps lifecycle events into TurnStreamEvent
  -> session_runtime.controller relays them to host
```

这里再补一条对 AI coding 非常关键的实现约束：

- 如果某段逻辑需要同时读写 `replay_index`、`completion_index`、lane 队列和 sibling cancellation 状态，它应属于 `tool_orchestration.py`。
- 如果某段逻辑需要同时访问 schema、validation、hooks、permission engine 和 `updated_input`，它应属于 `tool_resolution.py`。
- 如果某段逻辑主要在处理 provider capability profile、stream finalize boundary 和 tier downgrade，它应属于 `tool_executors.py`。
- 如果某段逻辑只是把 tool runtime 的 typed event 往 turn/session/host 边界上传递，它应留在 `turn_engine` / `session_runtime` / `hosts`，而不是反向污染 tool runtime 领域。

增量迁移时也建议按“先定 ownership，再搬实现”的顺序做，而不是先复制代码再事后清理。比较稳的迁移路径是：

1. 先在 `definitions.py` 和新增 `tool_lifecycle.py` 固定领域类型。
2. 再从 `tool_runtime.py` 抽出 `tool_resolution.py`，让“单次调用如何被 resolve”先独立。
3. 再引入 `tool_orchestration.py` 承接 replay / lane / sibling failure。
4. 最后在 `turn_engine/engine.py` 接入 `tool_executors.py` 的 tier selector，并将 lifecycle event 透出给 `session_runtime` / `hosts`。

Alternatives considered:

- 继续把所有新增概念堆进 `tool_runtime.py`。拒绝，因为这个文件已经同时承担 definition、context、scheduler、execute helper，多加 replay/lifecycle 只会继续失控。
- 把 replay 和 lifecycle 逻辑直接塞进 `turn_engine/engine.py`。拒绝，因为 turn engine 的职责应该是 request/stream orchestration，不是 tool runtime policy 引擎。
- 把 `ResolvedPermissionDecision` 放进 `permissions/models.py` 当成通用权限对象。拒绝，因为它依赖 tool call resolution 语境，离开 `ResolvedToolCall` 并不成立。
- 让 host adapter 自己从 `TurnStreamEvent.message` 反推 tool lifecycle。拒绝，因为这会重新把 typed event contract 降级成 transcript scraping。

### 10. 实现切分图

为了让后续实现能按 slice 前进，而不是一次性重写整个 tools 子系统，建议把落地路径固定成下面这张切分图：

```text
Slice A: Domain Contracts
  definitions.py
  tool_lifecycle.py [new]
  turn_engine/models.py
        |
        v
Slice B: Resolution Pipeline
  tool_resolution.py [new]
  permissions/engine.py
  tool_runtime.py (compat glue only)
        |
        v
Slice C: Batch Orchestration Core
  tool_orchestration.py [new]
  tool_runtime.py (legacy bridge)
  turn_engine/engine.py (batch integration only)
        |
        +-------------------+
        |                   |
        v                   v
Slice D: Turn Event Wiring  Slice E: Tier Selector + Buffered/Batch
  turn_engine/models.py       tool_executors.py [new]
  turn_engine/engine.py       turn_engine/engine.py
  session_runtime/controller.py
  hosts/base.py
        \                   /
         \                 /
          +-------+-------+
                  |
                  v
Slice F: FullStreaming Early Start
  tool_executors.py
  tool_orchestration.py
  turn_engine/engine.py
                  |
                  v
Slice G: Builtin Semantics + Compat Hardening
  builtins/tools.py
  builtins/tool_impls.py
  definitions.py
```

各 slice 的建议目标如下：

| Slice | Goal | Primary files | Ready when |
|-------|------|---------------|------------|
| A | 固定 richer contract、lifecycle objects、typed event surface | `definitions.py`, `tool_lifecycle.py`, `turn_engine/models.py` | 类型面稳定，现有 runtime 仍可通过 compat path 运行 |
| B | 把单次 tool call 的 normalize/validate/hooks/permission/semantics 收敛成 `ResolvedToolCall` | `tool_resolution.py`, `permissions/engine.py`, `tool_runtime.py` | success / denied / invalid 都能产出结构化 `ResolvedToolCall` |
| C | 在 batch path 上先跑通 orchestrator、lane、replay、`ToolOutcome`、lifecycle events | `tool_orchestration.py`, `tool_runtime.py`, `turn_engine/engine.py` | 即便没有 early start，batch tier 也走同一 lifecycle object model |
| D | 把 tool lifecycle 作为 first-class turn event 透给 session/host | `turn_engine/models.py`, `turn_engine/engine.py`, `session_runtime/controller.py`, `hosts/base.py` | host 不再需要从 transcript 反推 lifecycle |
| E | 接入 normalized capability selector 与 `Buffered` / `Batch` tier | `tool_executors.py`, `turn_engine/engine.py` | downgrade 可观察，lower tiers 保持同一 orchestration semantics |
| F | 落地 `FullStreaming` early start 和运行期 downgrade | `tool_executors.py`, `tool_orchestration.py`, `turn_engine/engine.py` | finalized streamed `tool_use` 可在 `message_stop` 前启动 |
| G | builtin tool semantics opt-in 与 legacy compat 清理 | `builtins/tools.py`, `builtins/tool_impls.py`, `definitions.py` | shell-like tools 有明确 failure policy，legacy tools 仍可执行 |

推荐的实现顺序不是“先把所有 executor 都做完”，而是：

1. 先把 A/B/C 做到 batch tier 可运行。
2. 再做 D，让 host/test harness 先看到 typed lifecycle。
3. 再做 E，把 provider capability selector 与 downgrade 接上。
4. 最后做 F/G，释放 full streaming 收益并收紧 builtin semantics。

这个顺序的核心原因是：batch tier 先跑通 lifecycle object model 与 replay buffer，后面的 `Buffered` / `FullStreaming` 只是在“何时观察到 envelope、何时允许开始执行”上更强，而不应该重新发明另一套 tool runtime。

### 11. 状态转移表

上面的概念状态机还可以进一步压成实现时可直接断言的 transition matrix。建议固定如下：

| Current Stage | Input event | Guard / condition | Owner | Required side effects | Next Stage |
|---------------|-------------|-------------------|-------|------------------------|------------|
| `none` | `envelope_observed` | parseable `tool_use` reached observation boundary | executor / orchestrator | allocate `ToolCallEnvelope`, freeze `replay_index` | `observed` |
| `observed` | `resolution_started` | envelope admitted to resolution | orchestrator | emit lifecycle event | `resolving` |
| `resolving` | `resolution_completed` | resolved as `denied` or `invalid` | resolution pipeline | materialize non-executable `ResolvedToolCall` | `resolved_non_executable` |
| `resolving` | `resolution_completed` + `execution_queued` | resolved as `executable` | resolution pipeline + orchestrator | materialize executable `ResolvedToolCall`, assign lane, enqueue | `queued` |
| `queued` | `execution_started` | scheduler admits lane | orchestrator / executor | create running task, emit lifecycle event | `running` |
| `queued` | `outcome_recorded` | cancelled before start or blocked by fatal sibling failure | orchestrator | create terminal `ToolOutcome`, assign `completion_index` | `terminal_pending_replay` |
| `running` | `progress_emitted` | tool emits progress | executor / tool runtime | emit progress lifecycle event only | `running` |
| `running` | `outcome_recorded` | success / error / cancelled execution | executor / orchestrator | create terminal `ToolOutcome`, assign `completion_index` | `terminal_pending_replay` |
| `resolved_non_executable` | `outcome_recorded` | synthetic denied / invalid terminal outcome | orchestrator | create terminal `ToolOutcome` without entering execute path | `terminal_pending_replay` |
| `terminal_pending_replay` | `replay_committed` | contiguous replay window available | orchestrator / turn engine | append ordered result to continuation history | `replayed` |
| `replayed` | none | terminal | n/a | none | `replayed` |

对于实现来说，最需要防回归的不是“能不能到达终态”，而是下面这些跳步必须永远不允许：

| Forbidden jump | Why it is invalid |
|----------------|-------------------|
| `resolving -> running` | 这会绕过 lane assignment、queued state 和 replay ordering |
| `resolved_non_executable -> running` | denied / invalid call 不应进入 execute path |
| `queued -> replayed` | 没有 terminal outcome 就提交 transcript，会丢失 host/test 可观察性 |
| `running -> replayed` | replay 必须消费 `ToolOutcome`，不能直接消费运行结果 |
| `terminal_pending_replay -> queued` | terminal call 绝不能被重新排队 |

如果要把这张表翻译成代码级断言，建议至少有两层：

- `tool_orchestration.py` 里对内部 state map 做 transition guard。
- golden/integration tests 对 `ToolLifecycleEvent` 序列做外部可观察断言。

### 12. 最小测试矩阵

这个 change 的 P0 不是“覆盖所有工具”，而是确保 richer contract、lifecycle model、replay semantics 和 downgrade path 不会退化。最小测试矩阵建议如下：

| Test ID | Scope | Fixture / setup | Must assert |
|---------|-------|-----------------|-------------|
| `T1_resolution_allow_updated_input` | unit | fake tool + hook rewrite + permission `updated_input` | `ResolvedToolCall.execution_input` 使用最终 input；`ResolvedPermissionDecision` 为 `PermissionAllowed`；semantics 只基于最终 input 求值 |
| `T2_resolution_denied_non_executable` | unit | fake tool whose permission mediation returns deny | 产出 `ResolvedToolCall(resolution_status="denied")`；不出现 `execution_started`；后续有 synthetic terminal `ToolOutcome` 占住 replay slot |
| `T3_batch_replay_ordering` | integration | batch tier, two concurrency-safe tools reverse completion order | `completion_index` 乱序，但 `replay_committed` 与 transcript 中的 `tool_result` 按 `replay_index` 顺序出现 |
| `T4_lane_conservative_downgrade` | unit | concurrency-safe tool lacking reliable conflict domain | lane 被降级成 `exclusive` 或 coarse serialized lane，而不是乐观并发 |
| `T5_fatal_sibling_cascade` | integration | one fatal shell-like tool + one running sibling + one queued sibling | fatal call 失败后，running/queued siblings 获得明确 terminal outcome；replay 没有空洞 |
| `T6_context_update_apply_phases` | integration | tool outcome emits capability refresh + transcript attachment + memory append | `before_replay` update 先于 replay 生效，`with_replay` 与 result 对齐，`after_replay` 只在 replay commit 后发生 |
| `T7_lifecycle_event_ordering` | integration | happy-path executable tool call | event 序列至少为 `envelope_observed -> resolution_started -> resolution_completed -> execution_queued -> execution_started -> outcome_recorded -> replay_committed`，期间 progress 只插在 running 段 |
| `T8_executor_downgrade_selection` | integration | fake adapters with/without finalize boundary and streamed structured tool calls | selector 正确选择 `FullStreaming` / `Buffered` / `Batch`；运行期 downgrade 可观察 |
| `T9_legacy_trait_tool_compat` | integration | legacy trait-based tool with no richer semantics object | tool 仍可执行；compat adapter 能产出默认 resolved semantics 与 lifecycle objects |
| `T10_full_streaming_early_start` | golden / integration | streamed `tool_use` finalized before `message_stop` | tool 在 `message_stop` 前启动；ordered replay 仍稳定；剩余 assistant stream 不丢失 |

这些测试里，`T1`-`T9` 应视为这个 change 的最小可交付矩阵；`T10` 是 final rollout gate，也就是只有当 `FullStreaming` 路径真正接上后，整个 change 才算完全兑现 early-start 目标。

建议的测试落点如下：

```text
unit
  - tool_lifecycle.py projections / transition guards
  - tool_resolution.py allow/deny/invalid resolution cases
  - lane derivation and conservative downgrade rules

integration
  - batch / buffered executor wiring
  - replay ordering
  - sibling cancellation
  - context update apply phases
  - lifecycle event emission through turn_engine/session/host

golden
  - full streaming early start
  - downgrade observability
  - transcript + turn-event dual assertions
```

换句话说，这份最小矩阵不是在追求“测得多”，而是在保证任何一次实现回退都会至少打破一条高价值断言：要么打破 lifecycle ordering，要么打破 replay semantics，要么打破 provider-tier downgrade，要么打破 compat path。

## Risks / Trade-offs

- **[运行时复杂度上升]** streaming orchestration 明显比 batch scheduler 复杂。 → Mitigation: 保留 compatibility adapter，并用独立 orchestrator 模块隔离复杂度。
- **[provider 能力宣告不可靠]** 某些 adapter 可能声称支持 streaming tool calls，但运行期缺少稳定 finalize boundary 或中途退化。 → Mitigation: selector 之外再保留 runtime fallback，允许 executor 在当前 turn 内自动降级并记录实际 mode。
- **[时序回归风险]** early start、ordered replay 和 cancellation 很容易出现隐藏 race condition。 → Mitigation: 增加 golden fixtures，覆盖顺序、取消和 partial completion。
- **[兼容性漂移]** richer contract 如果处理不好，可能让现有 builtin tools 行为变化。 → Mitigation: 所有现有工具先通过 legacy adapter 迁移，再逐个 opt-in 到 richer semantics。
- **[host 事件面扩张]** progress / refresh 接入 host bridge 后，宿主需要处理更多事件类型。 → Mitigation: 采用增量事件类型，并保持默认 host adapter 的 noop/compat 行为。
- **[failure policy 误判]** 像 `bash` 这类工具的失败判定如果定义不清，会让 runtime 过度取消或取消不足。 → Mitigation: 在 spec 中固定 outcome taxonomy 和 fatal policy 触发条件，并增加负例测试。

## Migration Plan

1. 先引入 richer tool contract 和 legacy adapter，让现有工具仍可通过兼容层执行。
2. 为 model adapter 增加 capability profile，并新增 selector 在 `FullStreaming`、`Buffered`、`Batch` 三层 executor 之间选择执行模式。
3. 新增 `StreamingToolOrchestrator`，先在内部接入 turn engine 和测试 harness，不立即移除原 batch scheduler fallback。
4. 将 progress、refresh 和 failure taxonomy 接入 host bridge、execution policy state 与 tool result mapping。
5. 在 golden / conformance tests 覆盖通过后，再把主执行路径切换到 capability-selected executor stack。
6. 视结果保留或简化旧的 batch-only 路径，仅作为 compat route、最低 tier executor 或测试 fallback。

Rollback strategy:

- 如果 streaming orchestration 在实现中证明风险过高，可以暂时回退到 legacy scheduler path，同时保留 richer contract 和测试基线，不影响已有 query/message protocol 变更。

## Open Questions

- richer contract 的最终公开 API 是直接挂在 `ToolDefinition` 上，还是拆成单独的 semantics object 更清晰？
- capability refresh 是否允许影响同一 provider attempt 后半段的 tool visibility，还是只影响下一轮 continuation request？
- `renderToolUseMessage` / classifier hints 在第一版是只做 runtime contract 预留，还是连 host/default classifier 适配一起落地？
- capability profile 应该由 provider adapter 显式声明、由 runtime 启发式推断，还是两者结合？
