## Context

当前 runtime 已经有 `HookBus`、session-scoped registration、phase payload 和 `HookEffect` 聚合，但这些能力主要服务于现有 runtime 内部 wiring 和 skill-owned hooks。它们还没有形成一套面向 framework integrator 的完整扩展协议：hook 的注册来源不统一、可公开依赖的 phase 边界不稳定、definition-level authoring 只在 skill hooks 上相对成熟、动态注册与外部执行 handler 也没有被正式收敛为平台契约。

这次 change 的目标不是模仿某个 CLI 的“用户脚本平台”，而是把 runtime 内核当前已经存在的 hook seam 提升为正式的 extension surface。平台需要同时服务四类接入方：

- runtime / embedded host，希望在 session 和 host lifecycle 上注入业务逻辑
- framework user，希望在 turn / tool / recovery 流程中注入审批、审计、路由和上下文逻辑
- definition author，希望在 agent / skill authoring 中声明 hook 行为
- runtime 自己，希望把 memory、permissions、elicitation、diagnostics 等 control-plane concern 继续经由统一机制接入，而不是重新散落回主循环

约束也很明确：

- runtime 主循环必须继续保持 authoritative，不允许 hook adapter 直接篡改内部状态机
- 不同来源的 hooks 必须有稳定的 ownership、scope 和 cleanup contract，避免 session 泄漏
- 外部执行型 handlers 必须经过 policy / trust gate，不能默认与内存内 callback 等价
- phase surface 必须分层，避免把临时 internal implementation point 过早公开成长期 contract

## Goals / Non-Goals

**Goals:**

- 把现有 hook 机制定义为正式的 runtime hook configuration platform，而不是只保留 skill hooks 和内部 bus
- 明确 hook 的公开 phase、scope、owner、registration source 和 cleanup semantics
- 定义统一的 handler execution model，使 callback、HTTP、command、agent、prompt 等 handler 都能被转换为同一组 typed hook effects / decisions
- 为 runtime 主循环补齐 framework-oriented hook points，使接入方能够在 context assembly、request shaping、response handling 和 recovery decision 阶段注入业务逻辑
- 定义 deterministic aggregation、policy gate 和 diagnostics metadata，保证多 hook 同时命中时仍可预测、可审计
- 保持现有 skill hook 语义可兼容演进，而不是推翻现有 hook bus

**Non-Goals:**

- 不在这个 change 中实现所有 handler adapter 的完整执行器或 UI/CLI 配置界面
- 不把 filesystem watcher、worktree、plugin marketplace 一类产品事件作为第一优先级纳入 public kernel contract
- 不允许 hook 绕过 runtime state machine 直接修改 transcript store、private context carrier 或 host internals
- 不在这个 change 中重写 permission、memory、elicitation、compaction 的算法本身；这里只定义它们如何通过统一 hook platform 接入

## Decisions

### 1. 平台分层为 “kernel hook bus + authoring / adapter surfaces”

`HookBus` 保持为 runtime kernel 的执行内核，负责 phase dispatch、matching、effect aggregation、ownership 和 cleanup。新的“hook configuration platform”位于其外层，负责：

- 定义哪些来源可以注册 hooks
- 定义哪些 handler kinds 可以被 authoring / config surface 表达
- 把不同 handler kinds 适配为统一的 hook effect contract

这样可以避免把配置文件语法、外部执行逻辑和内核 phase dispatch 混在一起。

备选方案是直接把 `HookBus` 本身扩展为用户配置模型。拒绝这个方案，因为它会让内核执行器绑定具体 authoring format，后续很难同时支持 frontmatter、runtime config、host API 和 dynamic registration。

### 2. phase 分成三层稳定性：kernel public、control-plane public、internal

不是所有 runtime 节点都应立即对外公开。这次设计将 hookable phases 分成：

- `kernel public`
  - session / prompt / tool / stop / subagent / session-end 一类基础 lifecycle
- `control-plane public`
  - compaction、elicitation、context assembly、request shaping、recovery decision 等显式控制面阶段
- `internal`
  - 仅供 runtime 自己使用、可能频繁重构的细粒度步骤

对接入方只承诺前两层的长期稳定性。这样既能给业务方足够的注入点，又不会把当前实现细节永久锁死。

备选方案是继续只保留“参考实现兼容 phase”。拒绝，因为 framework user 真正需要的往往不是 CLI 产品事件，而是 runtime 决策点，例如 `PreModelRequest` 和 `RecoveryDecision`。

这次 change 还会发布一份 authoritative initial phase catalog。首批 phase 清单如下：

- `kernel public`
  - `SessionStart`
  - `UserPromptSubmit`
  - `PreToolUse`
  - `PostToolUse`
  - `PostToolUseFailure`
  - `Stop`
  - `SubagentStop`
  - `SessionEnd`
  - `Notification`
  - `Elicitation`
  - `ElicitationResult`
  - `PreCompact`
  - `PostCompact`
- `control-plane public`
  - `PreContextAssemble`
  - `PostContextAssemble`
  - `PreModelRequest`
  - `PostModelResponse`
  - `RecoveryDecision`
- `internal-only`
  - provider streaming 内部细粒度状态
  - tool replay bookkeeping 内部状态
  - sidecar cancellation / restart 的中间步骤
  - terminal projection / host bookkeeping 的临时中间节点

规则也会明确下来：

- catalog 中列出的 `kernel public` 和 `control-plane public` phase 是兼容性承诺面
- 未列入 catalog 的 phase 默认一律视为 `internal-only`
- 某个 internal phase 只有在被显式加入 catalog 后，才能成为外部 authoring / integration contract

首批 public phase 还会带一份 execution matrix，用来明确 payload、允许的 effect class 和 external handler policy：

| Phase | Tier | Payload Focus | Allowed Effect Classes | External Handler Policy |
| --- | --- | --- | --- | --- |
| `SessionStart` | kernel public | session-start metadata / config snapshot | `observe`, `sidecar` | callback required; external only if policy enables observe/sidecar |
| `UserPromptSubmit` | kernel public | prompt text / attachments / ingress metadata | `observe`, `transform`, `sidecar` | callback required; external only if policy enables transform-safe handling |
| `PreToolUse` | kernel public | normalized tool call input | `observe`, `transform`, `decide`, `sidecar` | callback required; external allowed when policy enables blocking/request-shaping hooks |
| `PostToolUse` | kernel public | tool result envelope | `observe`, `decide`, `sidecar` | callback required; external allowed when policy enables post-tool shaping |
| `PostToolUseFailure` | kernel public | tool failure envelope | `observe`, `sidecar` | callback required; external observe/sidecar only |
| `Stop` | kernel public | stop reason / terminal candidate | `observe`, `transform`, `decide`, `sidecar` | callback required; external allowed when policy enables continuation/blocking hooks |
| `SubagentStop` | kernel public | child terminal status / metadata | `observe`, `sidecar` | callback required; external observe/sidecar only |
| `SessionEnd` | kernel public | final session status / cleanup context | `observe`, `sidecar` | callback required; external observe/sidecar only |
| `Notification` | kernel public | runtime notification envelope | `observe`, `sidecar` | callback required; external observe/sidecar only |
| `Elicitation` | kernel public | elicitation request envelope | `observe`, `decide`, `sidecar` | callback required; external allowed when policy enables response-producing hooks |
| `ElicitationResult` | kernel public | elicitation result envelope | `observe`, `sidecar` | callback required; external only if policy enables result shaping |
| `PreCompact` | kernel public | compaction trigger / pressure inputs | `observe`, `sidecar` | callback required; external observe/sidecar only |
| `PostCompact` | kernel public | compaction output / summary metadata | `observe`, `sidecar` | callback required; external observe/sidecar only |
| `PreContextAssemble` | control-plane public | raw turn inputs before context assembly | `observe`, `transform`, `sidecar` | callback required; external observe/sidecar only |
| `PostContextAssemble` | control-plane public | assembled prompt/runtime context envelope | `observe`, `transform`, `sidecar` | callback required; external only if policy enables context shaping |
| `PreModelRequest` | control-plane public | final model request envelope | `observe`, `transform`, `decide`, `sidecar` | callback required; external allowed when policy enables request overrides or gating |
| `PostModelResponse` | control-plane public | materialized provider response before continuation | `observe`, `transform`, `sidecar` | callback required; external allowed when policy enables response shaping |
| `RecoveryDecision` | control-plane public | normalized recovery inputs / candidate transition | `observe`, `transform`, `decide`, `sidecar` | callback required; external allowed when policy enables recovery advice or gating |

这里的约束是：

- `observe` 只允许产生 diagnostics / metrics / audit-style effects，不改变 main-loop outcome
- `transform` 只允许改写该 phase 明确定义的输入或 envelope，不允许越权修改 runtime state machine
- `decide` 只允许出现在 catalog 明确允许 block / continue / override 的 phase 上
- external handler policy 是 phase contract 的一部分，不是接入方可随意忽略的建议

除了 execution matrix，每个 public phase 还需要一份 minimum payload schema。这里的目标不是冻结内部 dataclass，而是约束每个 public phase 至少要暴露哪些稳定字段。首批 minimum payload baseline 如下：

| Phase | Minimum Required Fields |
| --- | --- |
| `SessionStart` | `session_id`, `config_snapshot` |
| `UserPromptSubmit` | `session_id`, `turn_id`, `prompt`, `attachments` |
| `PreToolUse` | `session_id`, `turn_id`, `tool_name`, `tool_input` |
| `PostToolUse` | `session_id`, `turn_id`, `tool_name`, `tool_input`, `tool_result` |
| `PostToolUseFailure` | `session_id`, `turn_id`, `tool_name`, `tool_input`, `error_message` |
| `Stop` | `session_id`, `turn_id`, `reason` |
| `SubagentStop` | `session_id`, `turn_id`, `agent_name`, `status` |
| `SessionEnd` | `session_id`, `final_status` |
| `Notification` | `session_id`, `message`, `level` |
| `Elicitation` | `session_id`, `prompt`, `kind` |
| `ElicitationResult` | `session_id`, `prompt`, `response` |
| `PreCompact` | `session_id`, `token_count` |
| `PostCompact` | `session_id`, `summary_id` |
| `PreContextAssemble` | `session_id`, `turn_id`, `active_messages`, `attachment_descriptors`, `runtime_metadata_view` |
| `PostContextAssemble` | `session_id`, `turn_id`, `prompt_context_envelope`, `context_generation`, `request_input_view` |
| `PreModelRequest` | `session_id`, `turn_id`, `context_generation`, `request_envelope`, `request_metadata` |
| `PostModelResponse` | `session_id`, `turn_id`, `request_id`, `provider_stop_reason`, `usage`, `response_envelope` |
| `RecoveryDecision` | `session_id`, `turn_id`, `attempt_index`, `recovery_input`, `candidate_action`, `failure_class` |

字段级 contract 还有三条边界：

- 上表中的字段是每个 public phase 的 minimum required fields，具体实现可以增加字段，但不能删掉这些稳定字段
- public payload 允许暴露“view”或“envelope”，不要求直接泄露 runtime private context 或 provider-native raw state
- 任何会泄露 private-only carrier、secret material、host handle 或 mutable runtime internals 的字段，都必须通过 redacted/stable public view 暴露，而不能直接进入 public payload schema

除了 payload schema，每个 public phase 还需要一份 concrete stable effect field contract。这里的目标是明确统一 `HookEffect` 里哪些字段在某个 phase 上是 framework user 可以依赖的 portable public behavior，而不是默认把所有 effect 字段都开放给所有 phase。首批 conservative effect-field matrix 如下：

| Phase | Allowed Stable Effect Fields |
| --- | --- |
| `SessionStart` | `additional_context`, `notifications`, `metadata` |
| `UserPromptSubmit` | `additional_context`, `notifications`, `metadata` |
| `PreToolUse` | `updated_input`, `continue_execution`, `notifications`, `metadata` |
| `PostToolUse` | `continue_execution`, `notifications`, `metadata` |
| `PostToolUseFailure` | `notifications`, `metadata` |
| `Stop` | `additional_context`, `continue_execution`, `stop_disposition`, `notifications`, `injected_messages`, `request_override`, `metadata` |
| `SubagentStop` | `notifications`, `metadata` |
| `SessionEnd` | `notifications`, `metadata` |
| `Notification` | `notifications`, `metadata` |
| `Elicitation` | `elicitation_result`, `notifications`, `metadata` |
| `ElicitationResult` | `notifications`, `metadata` |
| `PreCompact` | `notifications`, `metadata` |
| `PostCompact` | `notifications`, `metadata` |
| `PreContextAssemble` | `additional_context`, `notifications`, `metadata` |
| `PostContextAssemble` | `additional_context`, `request_override`, `notifications`, `metadata` |
| `PreModelRequest` | `continue_execution`, `request_override`, `notifications`, `metadata` |
| `PostModelResponse` | `request_override`, `injected_messages`, `notifications`, `metadata` |
| `RecoveryDecision` | `continue_execution`, `request_override`, `injected_messages`, `metadata` |

这个字段级 matrix 还要配三条更硬的边界：

- 某个 phase 未列出的 effect 字段，不构成该 phase 的 portable public behavior；即使当前内部实现偶然透传了这些字段，外部 authoring 也不能依赖它
- declarative registration、adapter manifest 和 generated definition 若声明会产出超出 matrix 的 effect 字段，必须在激活前被拒绝；对于 callback 这类运行时动态返回，runtime 至少要把超出 contract 的字段视为 ignored-with-diagnostics，而不是 silently portable
- 新增 public effect 字段必须先更新 phase contract，再允许 host、framework user 或 definition author 把它当作稳定依赖

#### Public phases 还需要映射到稳定的 main-loop layers

除了 stability tier，public phase 还需要有一个“在主循环哪一层触发”的稳定视图。tier 解决的是兼容性承诺；layer 解决的是接入方应在哪个 runtime boundary 介入，以及 effect 会在什么时候被真正消费。首批 layer model 如下：

```text
SessionStart
  └─ Turn ingress / context prep
     ├─ PreCompact -> PostCompact?
     ├─ UserPromptSubmit
     ├─ PreContextAssemble -> PostContextAssemble
     └─ PreModelRequest
        └─ Model attempt / response materialization
           └─ PostModelResponse
              ├─ Tool path: PreToolUse -> PostToolUse | PostToolUseFailure
              │              └─ RecoveryDecision
              └─ Stop path: Stop
                             └─ RecoveryDecision

Cross-cutting:
- Notification
- Elicitation -> ElicitationResult
- SubagentStop

Terminal:
- SessionEnd
```

对应的稳定 layer / phase / apply-point 关系如下：

| Main-loop Layer | Public Phases | Stable Trigger Boundary | Canonical Effect Apply Point |
| --- | --- | --- | --- |
| session lifecycle | `SessionStart`, `SessionEnd` | session controller 完成启动或结束清理 | 只允许 session 级 observe/sidecar 结果进入 diagnostics、notifications、startup/shutdown side effects，不允许改写 turn state machine |
| turn ingress and context prep | `PreCompact`, `PostCompact`, `UserPromptSubmit`, `PreContextAssemble`, `PostContextAssemble` | turn 进入 prepare/build-request 之前与期间 | `additional_context` 只能在 prompt/context envelope 冻结前并入；`request_override` 只能作为 pending override 进入 canonical request-shaping path |
| attempt request shaping | `PreModelRequest`, `PostModelResponse` | provider request 发出前，以及 provider response materialize 后但 continuation 未定前 | `request_override`、`continue_execution`、`injected_messages` 只能进入 canonical request/recovery handling，不允许越过状态机直接操作 provider adapter 或 transcript |
| tool execution boundary | `PreToolUse`, `PostToolUse`, `PostToolUseFailure` | normalized tool call 执行前后 | `updated_input` 只在 tool executor 调用前生效；`continue_execution` 只决定当前 tool call/result 是否允许继续进入后续 path |
| terminal and recovery | `Stop`, `RecoveryDecision` | no-tool terminal candidate 出现后，以及 recovery transition commit 前 | `stop_disposition`、`request_override`、`injected_messages`、`continue_execution` 必须先转换为 canonical recovery decision，再决定继续、重试、阻断或终止 |
| cross-cutting interactive and side-channel | `Notification`, `Elicitation`, `ElicitationResult`, `SubagentStop` | runtime 发出通知、请求用户输入、收到输入结果、或 child execution 结束 | `notifications` 直接进入 host-visible notification path；`elicitation_result` 只能满足当前 elicitation request，不能直接绕过 turn/recovery contract |

这里还需要明确两个约束：

- 某个 phase 的 layer 是 public contract 的一部分；后续若实现重构，只要 phase 仍属同一 public contract，就不能把它静默移动到更晚或更早、会改变 business logic 语义的 boundary
- cross-cutting phase 可以与主循环并列存在，但它们依然要声明“effect 在哪一个 canonical subsystem 生效”，避免出现 callback 返回了结果却没有清晰消费点的半公开语义

### 3. handler kinds 采用 “callback first, external adapters second”

平台上的规范 handler kinds 分为：

- `callback`
  - in-process、trusted、typed、首选的 framework integration surface
- `http`
  - 用于远程业务系统或 policy service
- `command`
  - 用于本地脚本、legacy automation 或隔离式 sidecar
- `agent`
  - 用于把较重的分析或验证逻辑委托给独立 agent execution
- `prompt`
  - 用于轻量模型判断或 prompt-driven classification

其中 callback 是规范语义的基线；其他类型都通过 adapter 转换到统一的 effect contract，并接受更严格的 timeout / failure / trust gate。

备选方案是把 command 作为主抽象。拒绝，因为这会把平台重心带回 CLI 自动化，而不是 runtime framework 扩展。

### 4. effect contract 按能力分组，而不是只按 before/after 划分

平台上的 hooks 不只是在某个事件前后“跑一下”，它们需要表达不同能力：

- `observe`
  - 只读诊断、审计、指标
- `transform`
  - 改写 context、request、tool input
- `decide`
  - 允许 / 阻止 / 继续 / 请求 override / 要求恢复
- `sidecar`
  - 异步补充上下文、通知、artifact、背景结果

实现上仍然可以聚合到统一的 `HookEffect` / `HookDispatchResult`，但规范层要先承认这四类能力的不同约束。比如 observe hooks 不应影响主循环结果，而 decide hooks 必须进入 deterministic precedence。

备选方案是只保留布尔式 continue/block 语义。拒绝，因为这不足以支撑 routing、request override、business approval 和 background sidecar 这些框架场景。

### 5. registration surface 必须显式区分来源与 scope

这次平台将 registration source 与 scope 一起建模，至少覆盖：

- runtime-level static registrations
- host-level registrations
- agent / skill-owned definition registrations
- session-scoped dynamic registrations
- turn-scoped temporary registrations
- child execution inherited registrations

每个 registration 都必须可追溯到 owner，且具备明确 cleanup 边界。外层配置平台可以允许多来源并存，但进入 bus 后统一变成 ownership-aware registration。

备选方案是继续让每个 subsystem 自己决定是否 cleanup。拒绝，因为这会再次导致 hook 泄漏和行为不可审计。

### 6. authoring model 采用 “authoring envelope -> normalized registration -> active bus entry”

平台不能把每个 authoring surface 都直接暴露成 `HookBus.register(...)` 的薄封装，否则 runtime config、frontmatter、host API 和动态 API 很快就会各自长出一套不兼容字段。首批 public model 需要明确区分三层对象：

| Layer | Who writes it | Purpose | Stable Public Shape | Internal-only Resolution |
| --- | --- | --- | --- | --- |
| authoring envelope | runtime operator / host integrator / definition author / framework user | 表达“我要在哪个 phase 上挂什么 handler” | config document、frontmatter `hooks` block、typed registration request | loader context、raw parsed YAML、compatibility sugar |
| normalized registration | hook platform 内核前的一致模型 | 做 phase contract validation、scope/owner 归一化、policy gate 和 diagnostics attribution | source, owner, phase, scope, matcher, handler manifest, declared effect contract, inheritance, cleanup boundary | resolved callable object、adapter cache、execution token |
| active bus entry | session/turn 内真实参与 dispatch 的注册项 | 供 `HookBus` phase dispatch / aggregation / release 使用 | session-owned registration instance | concrete callable, session-local ordering index, once-removal bookkeeping |

这里有一个关键约束：`HookBus` 仍然是 session-scoped kernel。也就是说 runtime-level 和 host-level 并不是往 bus 里塞“全局 registration”，而是先作为 declaration template 存在，再在 session start 或 session attach 时物化成 session-owned active entry。

首批 public ingress surfaces 建议统一为：

| Ingress Surface | Primary Author | Canonical Authoring Shape | Normalized `source_kind` | Default Activation Scope |
| --- | --- | --- | --- | --- |
| runtime config | framework/runtime operator | `hooks.registrations[]` document | `runtime_config` | session-template |
| host API | embedded host | typed registration request | `host_api` | session-template 或 session |
| definition frontmatter | agent / skill / invocation author | `hooks.registrations[]` 或 legacy phase-keyed `hooks` mapping | `definition` | agent default `session`, skill/invocation default `turn` |
| session API | framework user / runtime service | typed registration request | `session_api` | session |
| turn API | workflow / approval / retry controller | typed registration request | `turn_api` | turn |

为了兼容现有定义加载路径，public authoring schema 需要允许两种输入形式并明确主次关系：

- canonical public shape 是 `hooks.registrations[]`
- 现有 phase-keyed mapping，例如 `hooks.PreToolUse.matcher/effect`，作为 compatibility input 保留，但必须在 validation 前先 up-convert 成 canonical registration

一个推荐的 declarative shape 如下：

```yaml
hooks:
  handlers:
    tool_audit_http:
      kind: http
      endpoint: https://policy.internal/hooks/tool-audit
      timeout_ms: 500
      response_contract: hook-effect-v1
  registrations:
    - id: audit-post-tool
      phase: PostToolUse
      match:
        target: "*"
      scope:
        lifetime: session
        inherit_to_children: false
      handler:
        ref: tool_audit_http
      contract:
        effect_fields: [notifications, metadata]
```

definition frontmatter 也应收敛到同一 authoring 形状；只是为了兼容已有内容，loader 仍可接受：

```yaml
hooks:
  PreToolUse:
    matcher: echo
    effect:
      updated_input:
        value: rewritten
```

但这种 phase-keyed shorthand 只应被视为 compatibility sugar，而不是长期的 canonical public schema。

归一化后的 registration model 至少需要这些稳定字段：

- `registration_id`
- `source_kind`
- `source_ref`
- `owner`
- `phase`
- `matcher`
- `scope`
- `cleanup_boundary`
- `inherit_to_children`
- `once`
- `handler_manifest`
- `declared_effect_classes`
- `declared_effect_fields`
- `timeout_ms`
- `policy_tags`
- `metadata`

其中有两条边界必须写清楚：

- declarative config 不允许直接序列化 raw callback/object；若要使用 `callback` handler，必须通过 host 提供的 stable binding name 或 binding registry 引用
- `resolved callable`、adapter connection pool、handler cache、dispatch ordering index、telemetry span id 等字段都属于 internal resolution state，不进入 public authoring schema

### 7. handler manifests 必须显式描述 transport 与 normalization contract

handler kind 不只是一个字符串标签。为了让 runtime config、frontmatter 和 host API 最终都能走同一 validation / execution path，平台需要一类独立的 `handler manifest`：

- `callback`
  - declarative surfaces 只引用 `binding`
  - imperative host/session/turn APIs 可以直接给 typed callable，但进入 normalized registration 后仍要变成 callback manifest
- `http`
  - endpoint、method、auth ref、timeout、retry policy、response contract
- `command`
  - argv、cwd policy、env policy、timeout、exit-code contract
- `agent`
  - target agent、input template、budget/timeout、result normalization
- `prompt`
  - prompt template、model binding、effort/budget、result normalization

manifest 层的目标不是暴露 transport 细节本身，而是明确“这个 handler 如何被调用、超时或失败时如何处理、输出如何归一化到 `HookEffect` contract”。这样 phase registration 和 handler invocation 可以解耦。

### 8. precedence contract 采用 “broad-to-specific ordering + field-specific merge”

多来源 hook 一旦进入同一个 phase，平台必须同时解决两件事：

- 哪些 registration 先执行、后执行
- 不同 effect 字段在冲突时按什么规则合并

首批 public contract 不建议直接暴露任意整数 `priority`。原因很简单：它会把 authoring surface 变成一组难以审计的全局抢占值，而且当前 runtime 也没有成熟的优先级治理模型。v1 更适合先发布一套稳定、可解释的 precedence ladder：

| Precedence Dimension | Rule | Why |
| --- | --- | --- |
| `source_kind` | `runtime_config` < `host_api` < `definition` < `session_api` < `turn_api` | 让更静态、更宽范围的声明先建立基线，更动态、更窄范围的声明后覆盖 |
| materialization / activation epoch | 先 materialize 的 registration 先执行 | 保证 session template、definition activation、运行时动态添加之间有稳定先后 |
| source-local declaration order | declarative `registrations[]` 按书写顺序；imperative API 按调用顺序 | 让 author 能在本地 source 内推断顺序 |
| internal tie-breaker | internal registration ordinal / id | 只用于兜底，不构成 public authoring surface |

这意味着：

- runtime config 和 host template 负责给 session 建立默认基线
- definition-owned hooks 在 definition 被激活时进入序列，默认位于静态 template 之后、动态 session/turn hook 之前
- session / turn 动态注册是最晚进入的，因此在 replace-style effect 上具有最高 public precedence

这里有一条故意保守的边界：

- source precedence 解决的是“组合顺序”，不是“安全信任等级”
- 如果 host 或 runtime 需要不可被覆盖的强约束，应该使用 policy / trust gate、internal-only enforcement 或更窄 public contract，而不是依赖把某个 source 排得更靠后

在这个 precedence ladder 之上，effect merge 还要按字段类别分别定义：

| Effect Field Class | Fields | Merge Rule |
| --- | --- | --- |
| append-style | `additional_context`, `notifications`, `injected_messages` | 按 precedence order 追加，保留稳定顺序 |
| replace-style | `updated_input`, `elicitation_result` | 最后一个 non-null winner 生效 |
| gate-style | `continue_execution` | `false` 优先生效；diagnostics 需要记录哪些 hook 共同导致 gate 关闭 |
| field-merge-style | `request_override` | 按字段逐项 merge，后者覆盖前者；`field_sources` 必须记录 winning source |
| ladder-style | `stop_disposition` | 按显式处置梯度聚合，而不是简单 last-writer-wins |
| diagnostics-only | `metadata` | 浅层 key merge；后者覆盖同名 key，但业务语义不得依赖 metadata 决胜 |

`stop_disposition` 的 public precedence 梯度在首批 contract 中固定为：

```text
ALLOW_TERMINAL < CONTINUE_SAME_TURN < BLOCK_SESSION < HALT_FAILURE
```

为了让这个 contract 真正可解释，还要明确 materialization 顺序：

```text
session start / attach
  -> materialize runtime_config templates
  -> materialize host_api templates
  -> activate definition-owned registrations as agent/skill/invocation enters scope
  -> append session_api registrations in call order
  -> append turn_api registrations in call order
```

这套顺序还要配两条边界：

- external handlers 即使异步完成，也不能按“谁先返回谁赢”决定最终结果；聚合必须回到 published precedence key
- v1 不提供 public arbitrary priority number；如果未来真的需要，也必须作为单独 contract 引入，而不是让 authoring surface 偷偷依赖 internal ordinal

### 9. policy / trust gate 作用于 handler class，不直接作用于 phase

phase 决定“什么时候可以注入”，handler class 决定“允许怎样执行”。因此 policy 主要约束：

- 是否允许外部执行型 handlers
- 哪些 phase 允许 external side effects
- 哪些 sources 可以注册高权限 hooks
- callback 与 external adapter 的 trust boundary 是否不同

这让接入方可以在同一 phase 上允许 callback、禁止 command/http，而不必整个 phase 全关。

备选方案是只做全局开关。拒绝，因为它无法满足企业场景下常见的“允许内存内 policy callback，但禁止本地 shell command”。

### 10. diagnostics contract 要成为平台的一等能力

hook 平台一旦进入业务主循环，接入方必须知道：

- 哪些 hooks 命中了
- 哪些来源/owner 参与了决策
- 哪些 effect 被采纳或被更高优先级覆盖
- precedence ladder 中哪一个 registration 或哪一个 field-level source 成为了 winner
- 哪个 handler 超时、失败或被 policy 拒绝
- 哪些 override / injected messages / continuation decisions 实际生效

因此 diagnostics 不能只停留在 debug logging，必须成为 host-visible metadata contract。

首批 public diagnostics schema 建议拆成两层：

| Diagnostics Layer | Purpose | Minimum Stable Fields |
| --- | --- | --- |
| registration inventory | 回答“当前 session/turn 上有哪些 active hook” | `registration_id`, `source_kind`, `source_ref`, `owner`, `phase`, `scope`, `handler_kind`, `matcher_summary`, `precedence_key`, `activation_state` |
| phase dispatch trace | 回答“这次 phase dispatch 里谁命中、谁被拒绝、谁赢了” | `dispatch_id`, `session_id`, `turn_id`, `phase`, `matched_registrations`, `blocked_registrations`, `ignored_effects`, `winner_summary`, `applied_outcome` |

这里的核心不是把所有内部日志都公开，而是让 host 至少能稳定看到以下几类信息：

- `matched_registrations`
  - 哪些 registration 命中了 phase/matcher，包含 `registration_id`、`owner`、`source_kind`
- `blocked_registrations`
  - 哪些 registration 因 policy / trust / timeout / adapter failure / phase contract violation 未参与最终生效
- `ignored_effects`
  - 哪些 effect field 因 phase contract 不支持、字段无效或被更高优先级覆盖而未生效
- `winner_summary`
  - replace-style 字段的 winning registration
  - `request_override.field_sources`
  - `stop_disposition` winner
  - `continue_execution=false` 的 contributing registrations
- `applied_outcome`
  - 最终真正进入 runtime canonical path 的结果摘要，例如 `continuation_blocked`, `request_override_applied`, `elicitation_satisfied_by_hook`, `notifications_emitted`

一个推荐的 host-visible trace shape 如下：

```yaml
hook_dispatch_trace:
  dispatch_id: hookdisp_123
  session_id: sess_1
  turn_id: turn_7
  phase: Stop
  matched_registrations:
    - registration_id: reg_runtime_stop_guard
      owner: runtime:guardrails
      source_kind: runtime_config
      precedence_key: "runtime_config/0/0"
    - registration_id: reg_turn_approval
      owner: workflow:approval
      source_kind: turn_api
      precedence_key: "turn_api/4/1"
  blocked_registrations: []
  ignored_effects: []
  winner_summary:
    stop_disposition:
      winner_registration_id: reg_turn_approval
      value: block_session
    request_override_field_sources:
      max_output_tokens_override: reg_runtime_stop_guard
  applied_outcome:
    continuation_blocked: true
    matched_hooks:
      - runtime:guardrails
      - workflow:approval
```

对这个 diagnostics schema，还要写清三条边界：

- diagnostics payload 必须区分 `matched`、`blocked`、`ignored`、`won`、`applied` 这五种状态，不能只给一个模糊的 `matched_hooks` 列表
- diagnostics 应默认暴露 stable summary，而不是强制 host 依赖 transport body、raw exception stack 或 provider-native blob；详细调试信息可以作为 optional verbose payload 存在
- 任何会泄露 secret、credential、private context carrier、raw callback object 或 host handle 的字段，都只能以 redacted reason / opaque reference 方式进入 diagnostics contract

此外，diagnostics contract 还需要和 runtime 最终结果做关联。首批 correlation points 应至少包括：

- tool denial / tool result denial
  - 让 `ToolCallResult.metadata` 可关联回 hook registration winner 或 matched set
- elicitation satisfied by hook
  - 让 `ElicitationResponse.metadata` 标识 hook-source satisfaction
- stop / recovery blocked continuation
  - 让 terminal / transition metadata 标识 `continuation_blocked`, `matched_hooks`, `request_override_applied`
- request override propagation
  - 让 host 能看到哪些 override field 实际被写入 resumable or next-attempt request path

### 11. public API surface 采用 “typed request -> stable handle -> query views”

既然这个平台的目标是 framework extension surface，而不是内部 `hook_bus` 细节透出，那么 public API 也不能直接让外部拿着 `HookBus` 自己 `register/release/dispatch`。v1 更合理的形状是三类对象：

| Public Object | Purpose | Minimum Stable Fields / Operations |
| --- | --- | --- |
| `HookRegistrationRequest` | 声明“注册什么 hook” | `phase`, `match`, `scope`, `handler`, `contract`, `owner_hint?`, `metadata?` |
| `HookRegistrationHandle` | 表示一次已归一化注册的生命周期 | `registration_id`, `source_kind`, `owner`, `phase`, `scope`, `activation_state`, `release()` |
| `HookInventoryQuery` / `HookDispatchTraceQuery` | 查询当前 active registrations 与历史 dispatch traces | `session_id`, `turn_id?`, `phase?`, `owner?`, `source_kind?`, `limit?`, `cursor?` |

推荐的 surface 分层如下：

| API Surface | Primary Consumer | Allowed Scope | Returns |
| --- | --- | --- | --- |
| runtime API | framework/runtime operator | runtime template, session-template | template handle / inventory / trace views |
| host API | embedded host | host template, session, turn | same contract as runtime/session, but host-bound |
| session API | workflow/service code in one active session | session, turn | active registration handle / inventory / trace views |
| turn API | approval/retry/step controller | turn | turn-scoped handle / trace views |

为了和现有 `runtime -> host -> session` 结构对齐，推荐的 surface 组织方式是：

- runtime
  - 注册 runtime-level / session-template hooks
  - 查询某个 session 的 hook inventory / dispatch traces
- host
  - 在 managed session 体系下代理 runtime/session surfaces，避免 host wrapper 和 runtime surface 分裂
- session
  - 在当前 active session 上注册 session-scoped / turn-scoped hooks
  - 查询当前 session 的 active hooks 和 recent dispatch traces

一个推荐的 typed API shape 如下：

```python
handle = session.register_hook(
    HookRegistrationRequest(
        phase="PreToolUse",
        match={"target": "echo"},
        scope={"lifetime": "turn"},
        handler={"kind": "callback", "binding": "rewrite_echo"},
        contract={"effect_fields": ["updated_input"]},
    )
)

inventory = session.list_hooks(
    HookInventoryQuery(phase="PreToolUse")
)

traces = session.list_hook_dispatch_traces(
    HookDispatchTraceQuery(phase="PreToolUse", limit=20)
)
```

这个 API model 还需要一套稳定的 handle contract：

| Handle State | Meaning |
| --- | --- |
| `pending_activation` | template 已创建但尚未 materialize 到目标 session/turn |
| `active` | registration 已进入 active inventory，后续 phase dispatch 可命中 |
| `released` | 被显式释放，不再参与后续 dispatch |
| `expired` | 因 turn/session scope 自然结束而失效 |
| `rejected` | 因 phase contract / policy / invalid scope 在激活前失败 |

其中几条行为边界必须明确：

- `release()` 必须幂等；对 `released` / `expired` handle 重复调用不能报不稳定错误
- turn-scoped handle 在 turn 结束后会自动进入 `expired`
- session close 会使 session/turn-scoped handles 失效，并清空 active inventory
- runtime/host template handle 的 release 必须至少阻止未来 materialization；是否级联撤销现有 session-owned descendants 必须是公开且一致的 contract，v1 建议默认级联

inspection API 也要保持保守而可用：

- `list_hooks(query)` 返回当前 inventory snapshot，而不是 live mutable object
- `list_hook_dispatch_traces(query)` 返回 stable summary view，支持 `limit` 与 `cursor`
- trace retention 至少覆盖 active session 与 close-boundary correlation；更长期持久化可选，但 retention policy 必须可发现

为了和当前已有 surface 对齐，host wrapper 还应遵守一条对称性约束：

- 如果 runtime 暴露 `session.visible_invocations()` / `session.invocation_diagnostics()` 这类 inspect API，那么 hook platform 也应提供对称的 inventory / trace inspection，而不是要求宿主直接下钻 `runtime_services.hook_bus`
- `BoundHostRuntime` 一类 host facade 不应重新发明 hook API 语义，而应代理同一套 typed request / handle / query contract

### 12. authoritative example pack 必须和 public contract 一起发布

如果只发布 phase catalog、authoring schema 和 diagnostics contract，而不发布一组 authoritative examples，接入方仍然很难判断以下问题的实际语义：

- template registration 何时 materialize 成 session-owned active entry
- host/session/turn 三种 programmatic API 在 scope 和 handle state 上有什么差异
- `request_override`、`continue_execution`、`stop_disposition` 这类 effect 究竟在哪个 canonical path 上生效
- diagnostics 里的 `matched`、`blocked`、`ignored`、`winner`、`applied` 应该长什么样

因此 v1 需要把 example pack 当成 public contract 的配套件，而不是 release 后再补的非权威文档。首批 authoritative examples 至少应覆盖四类场景。

#### Example A: runtime config baseline

这个例子用于说明最静态、最宽范围的基线 hook 应如何声明，以及它如何作为 session-template source 参与 precedence ladder。

```yaml
hooks:
  handlers:
    tool_audit_callback:
      kind: callback
      binding: audit_tool_result
  registrations:
    - id: base-tool-audit
      phase: PostToolUse
      match:
        target: "*"
      scope:
        lifetime: session
        inherit_to_children: false
      handler:
        ref: tool_audit_callback
      contract:
        effect_fields: [notifications, metadata]
      metadata:
        policy_domain: audit
```

这个例子至少要说明三件事：

- 该 registration 的 `source_kind` 是 `runtime_config`，它在 session attach 时 materialize 成 session-owned active entry，而不是作为全局常驻 bus entry 存在
- 它只能稳定地产生 `notifications` 和 `metadata`，即使 callback 内部返回了别的 effect 字段，也必须按 phase contract 处理为 ignored-with-diagnostics
- 当后续 `definition`、`session_api` 或 `turn_api` 也注册了 `PostToolUse` hooks 时，这个 registration 仍按 published precedence key 先执行，而不是靠“谁先返回”或 adapter transport 决定顺序

#### Example B: host API template registration

这个例子用于说明 embedded host 如何在不直接下钻 `hook_bus` 的前提下，为托管 session 建立 host-owned template hook。

```python
handle = host.register_hook(
    HookRegistrationRequest(
        phase="PreModelRequest",
        match={"target": "*"},
        scope={"lifetime": "session-template"},
        handler={"kind": "callback", "binding": "apply_enterprise_request_policy"},
        contract={"effect_fields": ["request_override", "metadata"]},
        owner_hint="host:enterprise-policy",
    )
)
```

这个例子至少要说明：

- host surface 使用和 runtime/session surface 对称的 `HookRegistrationRequest` / `HookRegistrationHandle` contract，而不是暴露 host-specific 特例
- `session-template` scope 的 handle 初始状态是 `pending_activation`；只有当目标 session materialize 时，对应 descendant registration 才进入 `active`
- `handle.release()` 默认应阻止未来 session 继续 materialize 该 template，且 v1 建议对已 materialize 的 descendants 级联 release

#### Example C: session / turn API dynamic registration

这个例子用于说明 session-scoped 和 turn-scoped 动态 hooks 如何并存，以及 narrow scope 如何在 precedence 上覆盖更宽的 baseline。

```python
session_guard = session.register_hook(
    HookRegistrationRequest(
        phase="PostContextAssemble",
        match={"target": "*"},
        scope={"lifetime": "session"},
        handler={"kind": "callback", "binding": "inject_enterprise_context"},
        contract={"effect_fields": ["additional_context", "metadata"]},
    )
)

turn_gate = turn.register_hook(
    HookRegistrationRequest(
        phase="PreToolUse",
        match={"target": "deploy"},
        scope={"lifetime": "turn"},
        handler={"kind": "callback", "binding": "require_change_ticket"},
        contract={"effect_fields": ["continue_execution", "notifications"]},
        metadata={"approval_type": "change-ticket"},
    )
)
```

这个例子至少要说明：

- session 和 turn surface 都走同一归一化路径；差异只体现在 `scope.lifetime`、cleanup boundary 和默认 owner attribution
- `turn_api` source 在 precedence ladder 上晚于 `session_api`，因此若两者在同一 replace/gate-style field 上冲突，应由 turn-scoped registration 成为 public winner
- `turn_gate` 在 turn 结束后必须自动进入 `expired`；inventory query 应能看到它的最终 lifecycle state，而不是无痕消失

#### Example D: stop / recovery approval end-to-end

这个例子用于说明 Stop 和 RecoveryDecision 两个 phase 如何组成业务审批或人工恢复流程，以及 diagnostics 如何把两次 dispatch 串起来。

```text
Stop phase
  -> reg_runtime_stop_guard(runtime_config) emits request_override.max_output_tokens=1024
  -> reg_turn_approval(turn_api) emits continue_execution=false + stop_disposition=BLOCK_SESSION
  -> canonical outcome: continuation_blocked=true, resumable_request_override persisted

RecoveryDecision phase
  -> reg_session_resume_policy(session_api) emits continue_execution=true
  -> reg_session_resume_policy(session_api) emits injected_messages=["Approval received"]
  -> canonical outcome: recovery resumes with persisted request_override applied to next attempt
```

对应的 host-visible trace summary 至少应类似：

```yaml
hook_dispatch_trace:
  dispatch_id: hookdisp_stop_123
  phase: Stop
  matched_registrations:
    - registration_id: reg_runtime_stop_guard
      source_kind: runtime_config
    - registration_id: reg_turn_approval
      source_kind: turn_api
  winner_summary:
    stop_disposition:
      winner_registration_id: reg_turn_approval
      value: BLOCK_SESSION
    request_override_field_sources:
      max_output_tokens: reg_runtime_stop_guard
  applied_outcome:
    continuation_blocked: true
    resumable_request_override:
      max_output_tokens: 1024
```

这个例子至少要说明：

- `Stop` phase 产生的 `request_override` 不能直接越过状态机生效，而是先进入 resumable or next-attempt request path
- `RecoveryDecision` 才是继续、阻断、重试或终止的 canonical commit point；Stop hook 不直接修改 terminal state machine
- diagnostics 需要能把 `continuation_blocked`、`matched_hooks`、`request_override_applied` 和后续恢复决策关联到具体 registration winner

### 13. 实现切片和 conformance test matrix 需要被显式发布

如果只有高层 goals 和一组笼统任务，后续实现很容易把 phase registry、authoring normalization、main-loop wiring 和 diagnostics trace 混在一起做，导致 public contract 虽然写了，但实现顺序和回归边界不清晰。v1 应把推荐切片顺序和最低 conformance matrix 一并发布。

推荐的实现切片如下：

| Slice | Primary Scope | Primary Modules | Exit Criteria |
| --- | --- | --- | --- |
| Slice 1 | public phase registry 与 per-phase validation | `src/runtime/hooks/`, definition/config validators | 能区分 `kernel public` / `control-plane public` / `internal-only`，且非法 phase、非法 effect field 会在激活前拒绝 |
| Slice 2 | normalized registration model 与 canonical authoring schema | config loader、definition loader、registration normalization path | `hooks.registrations[]`、legacy phase-keyed hooks、programmatic request 都能归一化成同一 registration model |
| Slice 3 | `callback` canonical execution path 与 typed handles | runtime/host/session/turn public APIs、binding registry | `HookRegistrationRequest`、`HookRegistrationHandle`、inventory query 和 callback binding resolution 可稳定工作 |
| Slice 4 | main-loop public phase wiring 与 canonical effect consumption | `turn_engine`, `tool_runtime`, `elicitation`, `session_runtime` | `PreContextAssemble`、`PostContextAssemble`、`PreModelRequest`、`PostModelResponse`、`RecoveryDecision` 接入完成，且 effect 经 canonical path 消费 |
| Slice 5 | diagnostics inventory / dispatch trace / correlation | runtime services、host-visible metadata、trace retention path | `matched`、`blocked`、`ignored`、`winner`、`applied` 五类信息可查询，并能关联 tool denial / stop recovery / request override |
| Slice 6 | external adapters 与 policy/trust gate | adapter layer、policy enforcement、timeout/failure mapping | `http`、`command`、`agent`、`prompt` 至少能被明确允许/拒绝并归一化输出，且失败不会破坏 callback baseline |

这套切片还有两个实施边界：

- 不应在 Slice 1-3 之前先铺开所有 external adapter；`callback` 必须先成为规范语义的 baseline
- diagnostics 不能等全部功能完成后再补；最迟在 Slice 5 前，前面每一 slice 就要开始产出可核对的 winner attribution 和 blocked/ignored reason

首批 conformance test matrix 不要求对 `phase x source_kind x handler_kind` 做全笛卡尔积，但要求每一类 public contract edge 至少有一条权威覆盖。建议最小矩阵如下：

| Scenario | Phase | Source Kind(s) | Handler Kind | Effect Focus | Expected Runtime Outcome | Expected Diagnostics |
| --- | --- | --- | --- | --- | --- | --- |
| public phase registry rejects internal phase | `internal-only` phase candidate | `runtime_config` | `callback` | registration validation | handle enters `rejected`; no activation | rejection reason includes `phase_not_public` |
| replace winner follows precedence ladder | `PreToolUse` | `definition` + `turn_api` | `callback` | `updated_input` | turn-scoped winner rewrites tool input | `winner_summary.updated_input` points to turn registration |
| field-level merge keeps source attribution | `PreModelRequest` | `runtime_config` + `session_api` | `callback` | `request_override` | request emits merged override fields | `request_override.field_sources` records each winning registration |
| tool denial remains traceable | `PreToolUse` | `session_api` | `callback` | `continue_execution=false` | tool call is denied before execution | tool result metadata links `dispatch_id`, `matched_hooks`, `continuation_blocked=true` |
| elicitation can be satisfied by hook | `Elicitation` | `turn_api` | `callback` | `elicitation_result` | runtime consumes hook-provided answer without extra host round trip | elicitation metadata marks `satisfied_by_hook` and winner registration |
| unsupported effect field is ignored, not portable | `PostToolUseFailure` | `definition` | `callback` | unsupported `request_override` | runtime ignores invalid field and continues canonical failure path | trace contains `ignored_effects` with phase-contract reason |
| policy-blocked external handler is visible | `PostToolUse` | `host_api` | `http` | external observe/sidecar request | no external effect applied when policy denies | `blocked_registrations` includes `policy_denied` and handler kind |
| turn expiry and child inheritance are deterministic | child `PreToolUse` / parent inventory | `session_api` + `turn_api` | `callback` | scope cleanup / inheritance | child inherits session hook; completed turn releases turn hook | inventory shows inherited descendant plus expired turn handle |
| stop / recovery approval flow is correlated end-to-end | `Stop` + `RecoveryDecision` | `runtime_config` + `turn_api` + `session_api` | `callback` | `stop_disposition`, `continue_execution`, `injected_messages`, `request_override` | first dispatch blocks continuation, second dispatch resumes with preserved override | terminal/recovery metadata correlates both dispatches and winners |
| request override propagation survives boundary crossing | `PostContextAssemble` + `PreModelRequest` | `runtime_config` + `session_api` | `callback` | staged `request_override` propagation | override staged during context build is present in emitted request envelope | trace shows staged vs applied state and final field winners |

这张矩阵还应配两条执行规则：

- 每个 scenario 都要同时断言 runtime outcome 和 host-visible diagnostics，不能只测内部行为或只测 trace 序列化
- tool denial、elicitation satisfaction、request override propagation、stop/recovery continuation 是四条必须长期保留的 regression row，因为它们直接体现“业务逻辑注入 runtime 主循环”的平台价值

## Risks / Trade-offs

- `[Phase surface 过大]` → 先明确 public vs internal stability tiers，并允许部分 phase 只在 control-plane public 层暴露
- `[外部执行型 hooks 带来安全风险]` → callback 作为首选 surface，command/http/agent/prompt 默认经过 trust/policy gate，并支持按 handler class 关闭
- `[effect contract 过于复杂导致实现成本上升]` → 继续复用统一 `HookEffect` 聚合模型，只在 spec 层引入能力分组而不强制一次性重写内部数据结构
- `[多来源 hooks 叠加导致行为难以预测]` → 为 registration source、owner 和 effect precedence 定义确定性 contract，并要求宿主暴露 matched/effective diagnostics
- `[把内部实现细节过早冻结成外部 API]` → phase 稳定性分层，并把新增 phase 优先放入 control-plane public，而不是全部视作 kernel public
- `[authoring surfaces 各自演化导致 schema 漂移]` → 先定义 canonical registration schema 与 handler manifest，再让 runtime config、frontmatter 和 APIs 全部走 normalization

## Migration Plan

1. 保持现有 `HookBus`、`HookEffect` 和 skill-owned registration 语义兼容，先新增平台层 spec 与 registration model。
2. 先定义 canonical authoring schema、normalized registration model 和 handler manifest，让 runtime config、frontmatter 与 programmatic APIs 走同一 validation path。
3. 为 runtime / host / dynamic registration 补充正式 surface，同时让现有 definition loading 继续工作并兼容 legacy phase-keyed hook mapping。
4. 在主循环中逐步把 context assembly、request shaping、post-response handling 和 recovery decision 补成正式 hook points。
5. 为 callback 建立首个规范 execution path，再按 policy/trust contract 落地外部 adapter。
6. 将 diagnostics metadata 接到 host-visible surfaces，保证接入方可以验证 effective hook behavior。
7. 只有当新平台 surface 稳定后，才考虑收窄或废弃当前“已解析但未成熟”的 definition-level hook 语义。

## Open Questions

- `agent` 和 `prompt` handler 是否应作为首批 public adapter，还是先只把 `callback`、`http`、`command` 收敛成稳定 contract
- host lifecycle 是否最终进入同一个 `HookBus` phase 空间，还是继续作为 host runtime 的并列 lifecycle surface
- external adapters 返回的 effect 是否允许直接注入 `injected_messages`，还是只允许通过更受限的 continuation envelope 暴露
