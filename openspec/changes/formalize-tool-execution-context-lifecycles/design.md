## Context

当前 runtime 已经具备以下基础：

- `PromptContextEnvelope` 与 `RuntimePrivateContext` 已经把 prompt-visible 与 runtime-private carrier 拆开。
- `ToolContext`、`ToolCapabilityContext`、`ResolvedToolCall` 与 `ToolOutcome` 已经把 tool execution 拉进 runtime-managed capability 模型。
- `SessionController` 与 `TurnEngine` 已经分别承担 session control 与 turn orchestration 的主路径职责。

补充约束：

- 当前 authoritative top-level `openspec/specs/` 为空，因此本 change 使用新的 capability names 来正式定义这一层 contract，而不是对不存在的 archived capability 做 delta 修改。
- 现有 runtime 里已经存在事实上的 trust 分层：普通工具、强 runtime 耦合 built-ins、以及依赖当前混合 `ToolContext` 形状的遗留工具，但这些分层还没有被正式建模。

但这条链路仍然有一个明显的结构性缺口：工具执行的“公开 ABI”与“内部装配上下文”没有真正分离。当前 `ToolContext` 同时扮演：

- runtime 内部 wiring 容器
- turn-scoped capability holder
- tool execution ABI
- compatibility surface

结果是：

- public tool execution path 仍可直接触达 `runtime_services`、registries、runners 等内部对象；
- `app_state` 语义模糊，无法仅从结构上判断它是 session-scoped 还是 turn-scoped；
- `SessionController`、`TurnEngine` 与 tool execution path 之间虽然已有事实上的 owner 边界，但没有被正式建模成 `SessionScope` / `TurnScope` / call-scope；
- built-in privileged tools 与未来 user/third-party tools 共享同一上下文类型，导致 ABI 很难收窄。

这个 change 的目标不是重新设计整个 tool runtime，而是把已有能力收束成更稳定的边界。

## Goals / Non-Goals

**Goals:**

- 定义公开 `ToolExecutionContext` 与内部 `InternalToolContext` 的显式拆分。
- 明确 `SessionScope`、`TurnScope` 与 call-scope 的 owner、创建时机、共享规则与释放时机。
- 用结构表达 state lifetime：把当前模糊的 `app_state` 拆成显式的 session-scoped 与 turn-scoped state handles。
- 禁止 public tool ABI 依赖 raw `runtime_services`、registries 或 privileged runners。
- 禁止 public tool ABI 直接暴露完整 `RuntimePrivateContext`；如需暴露 runtime-private execution metadata，只能通过显式只读字段或窄投影。
- 明确 public tools、privileged built-in tools 与 legacy-compat tools 的分类规则与默认归类。
- 保留 built-in privileged tool 与 legacy tool 的兼容迁移路径，不要求一次性重写所有工具。
- 让新的上下文边界与现有 `RuntimePrivateContext`、query context、tool capability contract 对齐，同时把 trust routing authority 固定在 runtime-owned registration / assembly path。

**Non-Goals:**

- 不重写现有 tool orchestration state machine、permission engine、hook bus 或 model request protocol。
- 不在本 change 中引入新的 UI-specific callback surface。
- 不要求把所有 builtin tools 立即迁移到同一最低权限 public ABI。
- 不在本 change 中重新设计 MCP、plugin 或 invocation catalog provider 系统。

## Decisions

### 1. 将当前 `ToolContext` 降级为 internal-only 装配对象，并引入公开 `ToolExecutionContext`

公开给工具的上下文不再直接使用当前 `ToolContext`。新的分层为：

```text
SessionController / TurnEngine
  -> SessionScope
  -> TurnScope
  -> InternalToolContext
  -> ToolExecutionContext
  -> tool.execute(...)
```

语义上：

- `InternalToolContext`
  - 供 runtime 内部使用
  - 持有 registries、handlers、privileged runners、`runtime_services`
  - 可变，承担 wiring、compat、内部 hook/permission/orchestration 协调
- `ToolExecutionContext`
  - 供 public tool ABI 使用
  - call-scoped
  - 冻结 call identity、query metadata、resolved input/permission/semantics
  - 仅暴露 capability handles，不暴露 raw service bag
  - 若必须暴露 runtime-private execution metadata，只能通过显式只读字段或 `RuntimePrivateContextView`

Why:

- 这能把“runtime 如何装配工具执行”与“工具允许看到什么”分离开来。
- 也能避免后续继续把更多 privileged runtime capability 堆进 public ABI。

Alternatives considered:

- 继续扩展现有 `ToolContext`。拒绝，因为这会维持单一重型上下文，并继续模糊 public/internal 边界。
- 直接把 `ToolCapabilityContext` 当成 public ABI 而不保留 internal context。拒绝，因为 runtime 内部仍需要 registries、runners、compat wiring 和 privileged capability。
- 在 public `ToolExecutionContext` 上直接挂完整 `RuntimePrivateContext`。拒绝，因为这会重新把内部 carrier 变成默认 public surface，并破坏后续 capability narrowing。

### 2. 将 state lifetime 从“约定”改成“结构”：显式引入 `SessionScope` 与 `TurnScope`

新的 owner 模型如下：

- `SessionScope`
  - owner: `SessionController`
  - 包含 session-scoped state、session private context、memory access、internal read cache、task/session artifacts
- `TurnScope`
  - owner: `TurnEngine`
  - 包含 turn-scoped query snapshot、tool/skill pool snapshot、file state、progress、notifications、capability refresh、abort handle
- call-scope
  - owner: tool resolution / execution path
  - 通过 `ToolExecutionContext` 暴露
  - 冻结 `tool_use_id`、`replay_index`、canonical tool name、resolved execution-bound input、permission decision 等 call metadata

Why:

- 当前 `ToolContext.__post_init__()` 默认构造 state handle 的方式不够显式，难以从结构判断 ownership。
- 通过显式 scope 建模，可以把 state lifetime、reuse rules 和 disposal semantics 固定下来。

Alternatives considered:

- 继续保留单一 `app_state` 并通过 namespace 约定 session/turn 语义。拒绝，因为 lifetime 仍然不可见，测试与回归也更脆弱。

### 3. 用 `session_state` / `turn_state` 替代当前单一 `app_state`

public tool ABI 中不再暴露一个语义模糊的 `app_state`，而是显式暴露：

- `session_state`
- `turn_state`

这两个 handle 在 public ABI 上应当是两个不同的窄接口类型，例如：

- `SessionStateHandle`
- `TurnStateHandle`

它们可以保留接近的操作语义，例如 `get` / `set` / `compare_and_set`，但不应在 public contract 上退化成“同一个 `AppState` 类型 + scope label”。

`file_state` 仍保持独立 handle，因为它的职责不是一般性的 key-value state，而是：

- file snapshot / observation
- conflict key 归一化
- guarded/reserved path visibility

Why:

- `app_state` 作为单一抽象会把 lifetime 和 authority 问题重新推回“调用方约定”。
- `session_state` / `turn_state` 的拆分更适合你们当前 runtime 分层，也更适合后续 conformance test。
- 将它们保留为两个不同的 public handle 类型，可以在类型层和 ABI 层直接表达 lifetime 差异；即便底层共享同一个存储实现，也不影响公开 contract 的清晰度。

Alternatives considered:

- 维持 `app_state`，但增加 metadata 说明 scope。拒绝，因为读写接口本身仍然不反映生命周期。
- 在 public ABI 中复用同一个 handle 类型，仅靠 `scope` 字段区分。拒绝，因为它仍然允许调用侧把两种 lifetime 当成同一种 capability 处理，削弱结构边界。

### 4. `runtime_services` 只保留在 internal path，不进入 public tool ABI

`runtime_services` 仍然是 runtime 内部装配 spine，但不应再成为 public tool capability surface 的一部分。

新的原则：

- public tool ABI 只能通过显式 handles 访问标准 capability
- privileged built-in tools 可以继续通过 `InternalToolContext` 访问 internal services
- legacy tools 通过 compat adapter 承接，避免一次性迁移所有调用点

Why:

- raw `runtime_services` 会让 tool 绕过 policy ceiling、memory guard rails、host mediation 和 capability narrowing。
- public ABI 一旦暴露 service bag，后续就很难再收窄。

Alternatives considered:

- 彻底删除 `runtime_services`。拒绝，因为 internal runtime wiring 和 privileged built-ins 仍需要它。
- 保留 `runtime_services`，但文档上标记“不要用”。拒绝，因为这无法形成真正的 contract。

### 5. 明确工具 trust model：public / privileged / legacy-compat

这个 change 将工具执行路径固定为三类：

- `public`
  - 默认类别
  - 适用于 user-defined、external、future third-party tools
  - 只能拿到 `ToolExecutionContext`
- `privileged`
  - 仅适用于 runtime-owned built-in tools
  - 可经 internal adapter 使用 `InternalToolContext`
- `legacy-compat`
  - 迁移期类别
  - 适用于仍依赖当前混合 `ToolContext` 形状的旧工具
  - 通过 compat adapter 承接，但不作为新增工具默认入口

分类规则需要满足：

- 默认新增工具落到 `public`
- `privileged` 必须是显式标记，而不是在运行时根据访问行为隐式提升
- `legacy-compat` 必须是迁移期显式选择，不得成为 public ABI 的永久旁路
- trust classification 的 source of truth 必须位于 runtime-owned registration / assembly path
- definition frontmatter、tool self-description 或第三方 metadata 最多只能作为 hint，不能单独提升为 `privileged` 或 `legacy-compat`

Why:

- 这能把“工具能力边界”与“工具信任级别”同时固定下来。
- 也能避免 future tool 因为少数 runtime-owned built-ins 的需要而默认拿到过宽上下文。

Alternatives considered:

- 不做 trust model，全部统一走一个 ABI。拒绝，因为会继续把 privileged needs 外溢到 public path。
- 只区分 public / privileged，不单列 legacy-compat。拒绝，因为迁移期仍需要一个受控过渡层来承接旧 `ToolContext` 依赖。
- 让 tool definition/frontmatter 自声明 privileged routing。拒绝，因为 privilege authority 不能落在 tool self-description 上，否则 public path 会再次被绕开。

### 6. 区分 public tool ABI 与 privileged built-in tool ABI

不是所有工具都处于同一信任级别。这个 change 将显式承认两类执行路径：

- public tool path
  - user-defined / external / future third-party tools
  - 使用 `ToolExecutionContext`
- privileged built-in path
  - runtime pack 内部强耦合工具，如 agent/skill/task/ask-user 等
  - 可通过 `InternalToolContext` 或 internal adapter 使用 privileged services

Why:

- 这能在不污染 public ABI 的前提下，保留 runtime 自身 built-ins 的实现自由度。
- 也能避免为满足少数 privileged 工具，而把整个 public ABI 拉宽。

Alternatives considered:

- 强制所有工具统一走同一最低权限 ABI。拒绝，因为短期内会让 privileged built-ins 过度受限，并迫使 runtime 泄露更多 capability。

### 7. 迁移采用“先别名、再收口”的 compatibility 方案

迁移不应一次性替换所有 `ToolContext` 用法。推荐顺序为：

1. 引入 `SessionScope` / `TurnScope` / `ToolExecutionContext` 的正式结构
2. 让现有 `ToolContext` 持有 scope 引用，成为 `InternalToolContext` 的过渡形态
3. 在 resolve/execute 路径中派生 `ToolExecutionContext`
4. 逐步把普通工具迁移到 public ABI
5. 将 privileged built-ins 标记为 internal-only path
6. 最后收紧 `runtime_services` 在 tool path 的可见性

Why:

- 这能避免在一个 change 中同时打断 tool execution、built-ins 和 conformance tests。

Alternatives considered:

- 大爆炸迁移。拒绝，因为 runtime 现在已经有较多 built-ins 和 tests 依赖现有混合 ABI。

### 8. `read_cache` 在第一阶段只固定 ownership，不要求强制实现具体缓存

`SessionScope` 可以保留一个可选的 internal `read_cache` 槽位，但第一阶段不要求 runtime 必须引入新的 concrete cache backend。

第一阶段需要锁定的是：

- 若 runtime 拥有可跨 turn 复用的 read optimization / read cache，它属于 `SessionScope`
- 它是 internal-only 基础设施，不进入 public `ToolExecutionContext`
- 它可以按 session start 初始化，也可以 lazy init
- 若当前 runtime 没有 read cache，实现仍然符合本 proposal

Why:

- 当前代码库里并不存在一个明确、稳定的 session read cache 实现，把它作为第一阶段强制 deliverable 会把“结构定界”变成“凭空新增内部优化”。
- 先固定 ownership 与 visibility，能避免未来把 cache 误放进 turn-scope 或 public ABI，同时不扩大本 change 的实现面。

Alternatives considered:

- 在第一阶段强制实现 concrete `read_cache`。拒绝，因为这会把一个目前不存在的内部优化变成迁移阻塞项。
- 完全不在 design 中建模 read cache ownership。拒绝，因为未来一旦加入这类优化，很容易再次落到错误的 scope。

## Scope Ownership Matrix

| Scope / handle | Owner | Create | Share boundary | Dispose | Publicly visible |
| --- | --- | --- | --- | --- | --- |
| `SessionScope` | `SessionController` | session `start()` / resume | all turns in one session | session `close()` | no |
| `session_state` | `SessionScope` owner | with `SessionScope` | all turns in one session | session `close()` | yes |
| `session_private_context` | `SessionController` | session start + ingress/private updates | all turns in one session | session `close()` | read-only subset only |
| internal `read_cache` | session/runtime internal owner | session start or lazy session init | session-internal only | session `close()` | no |
| `TurnScope` | `TurnEngine` | admitted turn start | one admitted turn | terminal turn completion | no |
| `turn_state` | `TurnScope` owner | with `TurnScope` | one admitted turn | terminal turn completion | yes |
| `file_state` | `TurnScope` owner | with `TurnScope` | one admitted turn | terminal turn completion | yes |
| `progress` / `notifications` / `refresh_capabilities` / `abort_handle` | `TurnScope` owner | with `TurnScope` | one admitted turn | terminal turn completion | yes |
| `ToolExecutionContext` | call execution path | after resolution, before execute | one tool call | replay commit or terminal non-executable completion | yes |
| `InternalToolContext` | runtime internal execution path | when tool path is assembled | internal only | end of tool orchestration path | no |

## State Inventory

推荐的 state placement 如下：

- `SessionScope`
  - `session_state`
  - `session_private_context`
  - `memory_access`
  - optional internal `read_cache`
  - session-owned task/artifact registries
- `TurnScope`
  - query snapshot
  - `turn_state`
  - `tool_pool` / `skill_pool` snapshot
  - `file_state`
  - `progress`
  - `notifications`
  - `refresh_capabilities`
  - `abort_handle`
- call-scope / `ToolExecutionContext`
  - `tool_use_id`
  - `replay_index`
  - canonical tool name
  - resolved execution-bound input
  - resolved semantics
  - permission decision

原则：

- 需要跨 turn 复用的内容进入 `SessionScope`
- 只对当前 continuation authoritative 的内容进入 `TurnScope`
- 只对单次 tool call 稳定的元数据进入 `ToolExecutionContext`
- 若某项数据既无法解释为 session，也无法解释为 turn，则默认不放进 public state handles

## Compatibility Boundary

compat adapter 需要满足以下边界：

- 它可以承接 legacy tools 对旧混合 `ToolContext` 形状的依赖
- 它不能成为新增 public tools 获取 privileged capability 的默认入口
- 它必须有明确退出方向：普通工具迁移到 `ToolExecutionContext`，runtime-owned built-ins 迁移到 privileged internal path
- 文档与测试必须区分“compat path 仍可执行”与“public ABI 仍然很窄”这两件事，避免通过 compat path 重新扩宽 public contract

## Conformance Matrix

最低需要锁定以下行为：

- public tool path 无法直接访问 raw `runtime_services`
- public tool path 不直接获得完整 `RuntimePrivateContext`
- `session_state` 可跨 turn 复用，而 `turn_state` 不可跨 turn 复用
- `file_state` 在新 admitted turn 上重置 authoritative view
- 同一 turn 的多个 tool call 共享 turn-scoped handles，但 call metadata 冻结且彼此独立
- privileged built-in tool 可以继续执行，但不会因此把 privileged capability 暴露到 public ABI
- legacy-compat tool 可以继续执行，但 compat path 不能成为新增工具默认入口
- 非 runtime-owned tool 即使在 definition metadata 中自声明 privileged，也不会因此获得 privileged path

## Appendix: Recommended Dataclass Sketch

推荐结构草图如下，仅作为 shape 参考：

```python
@dataclass(slots=True)
class SessionScope:
    session_id: str
    agent_name: str
    cwd: Path
    private_context: RuntimePrivateContext
    session_state: SessionStateHandle
    memory_access: MemoryAccessHandle
    read_cache: Any = None


@dataclass(slots=True)
class TurnScope:
    session_id: str
    turn_id: str
    agent_name: str
    cwd: Path
    query: QueryContext
    private_context: RuntimePrivateContext
    tool_pool: tuple[Any, ...] = ()
    skill_pool: tuple[Any, ...] = ()
    turn_state: TurnStateHandle | None = None
    file_state: FileStateHandle | None = None
    progress: ProgressHandle | None = None
    notifications: NotificationsHandle | None = None
    refresh_capabilities: CapabilityRefreshHandle | None = None
    abort_handle: AbortHandle | None = None


@dataclass(slots=True)
class InternalToolContext:
    session: SessionScope
    turn: TurnScope
    tool_registry: Any = None
    agent_registry: Any = None
    skill_registry: Any = None
    runtime_services: Any = None
    permission_handler: Any = None
    ask_user_handler: Any = None
    agent_runner: Any = None
    skill_runner: Any = None


@dataclass(frozen=True, slots=True)
class ToolExecutionContext:
    call: ToolCallIdentity
    query: QueryContext
    permission_context: PermissionContextView
    session_state: SessionStateHandle | None = None
    turn_state: TurnStateHandle | None = None
    file_state: FileStateHandle | None = None
    memory_access: MemoryAccessHandle | None = None
    progress: ProgressHandle | None = None
    notifications: NotificationsHandle | None = None
    refresh_capabilities: CapabilityRefreshHandle | None = None
    abort_handle: AbortHandle | None = None
    private_context_view: RuntimePrivateContextView | None = None
```

## Risks / Trade-offs

- [dual ABI 增加短期复杂度] internal/public 两套 context 会在过渡期并存。 → Mitigation: 明确命名和 owner，避免继续在 `ToolContext` 上添加新 public capability。
- [state migration 容易引入 lifetime regression] 从单一 `app_state` 拆成 `session_state` / `turn_state` 可能引入遗留写入位置错误。 → Mitigation: 通过 spec + conformance tests 锁定跨 turn 与 turn-local 行为。
- [privileged built-in 例外路径可能被滥用] 一旦 internal path 没有约束，未来代码可能继续依赖它。 → Mitigation: 将 privileged path 限定在 runtime pack，并把 public tool ABI 作为默认新增工具入口。
- [compat adapter 存活过久] legacy surface 可能长期不被移除。 → Mitigation: 在 tasks 中显式要求新增 public tool path tests，并标记 legacy adapter 的目标收口阶段。
- [trust classification 规则若过于隐式会再次扩大 public path] → Mitigation: 将 `privileged` / `legacy-compat` 设为显式分类，并为默认归类建立 conformance tests。

## Migration Plan

1. 定义 `SessionScope`、`TurnScope`、`InternalToolContext`、`ToolExecutionContext` 的正式数据结构与 owner contract。
2. 在 `SessionController` 中显式创建/持有 `SessionScope`，并将 session-scoped resources 从隐式 metadata usage 中抽出。
3. 在 `TurnEngine` 中显式创建/持有 `TurnScope`，并将 turn-scoped handles 从默认构造改为 owner 注入。
4. 在 tool resolution / execution 路径中从 internal context 派生 `ToolExecutionContext`。
5. 为 public tool path 增加 capability-only execution surface；为 privileged built-ins 保留 internal adapter。
6. 逐步收紧 tool path 对 `runtime_services` 的直接访问，并补齐 conformance coverage。
7. 在 compat path 收敛后，移除普通工具对旧混合 `ToolContext` ABI 的依赖。

Rollback strategy:

- 若 public/internal split 需要回退，可先保留 `InternalToolContext` 对旧 `ToolContext` 字段布局的兼容映射。
- 不回退 prompt/private context 分层，不重新把 private carrier 混回 prompt-facing context。

## Remaining Open Questions

- None for this proposal revision. Remaining implementation details should be tracked under tasks and code review rather than left as contract-level ambiguity.
