## Context

当前 runtime 的主干已经是：

```text
RuntimeAssembly -> SessionController -> TurnEngine -> Tool/Agent/Skill runtimes
```

这条主链路方向正确，但还存在三个会持续放大复杂度的结构性缺口：

- session ingress 还没有独立边界。`SessionController` 仍然直接把 `InboundEvent` 归一化成 `RuntimeMessage` 并启动 turn，导致输入归一化、附件注入、local-only outcome 和 turn admission 都混在 session 主循环里。
- prompt-visible context 与 runtime-private context 仍然混用。`TurnEngine` 生成的 `runtime_context` 会一路传给 `ContextAssembler`，后者又把其中大部分直接拼入 system prompt，导致 policy、permission、diagnostics 等 runtime 私有状态泄露到模型可见层。
- lifecycle ownership 交叉。`SessionController.start()/close()` 直接调用 host startup/shutdown，而 `RuntimeAssembly` / `BoundHostRuntime` 也暴露 lifecycle surface；同时 `run_prompt()/stream_prompt()` 这类 one-shot helper 会创建并启动 session，却不保证 close 语义。

这个 change 不需要引入新的 monolithic `QueryEngine`。目标是保留当前更清晰的 Python 分层，同时把参考实现中真正值得吸收的三个边界补齐。

## Goals / Non-Goals

**Goals:**

- 在 `SessionController` 前建立明确的 session ingress 层，收敛 inbound normalization、session-only outcome 和 turn admission。
- 将模型可见 prompt context 与 runtime-private context 分离，防止私有控制面状态直接进入 prompt。
- 重新定义 host、runtime assembly、session controller 的 lifecycle ownership，让 startup/shutdown、session start/end 和 one-shot helper 形成一致 contract。
- 为 ingress、context boundary 和 lifecycle 行为建立可观察、可回归的协议面。

**Non-Goals:**

- 不重写 `TurnEngine` 的 turn-state machine，也不把 turn loop 合并回单个大类。
- 不在本 change 中重做 memory、hooks、compaction 的算法本身。
- 不要求一次性把所有 runtime metadata 都换成强类型对象；第一阶段允许通过收紧结构化 envelope + 兼容适配完成迁移。
- 不把 host UI 逻辑拉回 runtime core。

## Decisions

### 1. 引入独立的 `SessionIngressProcessor`

在 `SessionController` 与外部 inbound event 之间新增 ingress processor，输入是 `InboundEvent + SessionState snapshot + runtime services/context`，输出是结构化 `SessionIngressResult`。

这里不再使用松散 metadata bag，而是固定最小协议：

- `IngressAdmission`: `kind + reason + metadata`
- `IngressReplayOutput`: host-visible replay item，与 transcript message 分离
- `SessionIngressResult`:
  - `normalized_messages`
  - `replay_outputs`
  - `prompt_updates`
  - `private_updates`
  - `admission`

其中 `admission.kind` 至少覆盖：

- `admit_turn`
- `local_only`
- `transcript_only`
- `replay_only`
- `reject`

Why:

- 这使 session ingress 成为独立 contract，而不是 `SessionController` 里的若干条件分支。
- 后续补 slash/local command、task notification、host-generated system prompt、attachment expansion 时，都能走同一 ingress surface。
- 也让 transcript persistence、host replay 和 turn admission 的顺序变得清晰可测。

Alternatives considered:

- 继续把 ingress 逻辑留在 `SessionController`。拒绝，因为这会让 session control 与 input normalization 长期耦合。
- 把 ingress 下放到 host adapters。拒绝，因为那会让 interactive/headless host 重新分叉执行语义。

Ingress outcome matrix for the first implementation slice:

| inbound source | normalized_messages | replay_outputs | prompt_updates | private_updates | transcript write | start turn |
| --- | --- | --- | --- | --- | --- | --- |
| user prompt | yes | optional | optional | optional | yes | yes |
| slash/local command | optional | yes | no | optional | optional | no |
| host-generated prompt | optional | optional | optional | optional | ingress-defined | ingress-defined |
| task notification | optional | optional | no | optional | ingress-defined | only if admitted |
| reject | no | optional rejection output | no | optional diagnostics | no | no |

Notes:

- `host-generated prompt` 是 meta ingress input，不自动等价于普通 user text；它可以是 prompt-visible、replay-visible、private-only，或 admitted turn，完全由 ingress 决定。
- `slash/local command` 与 `task notification` 第一阶段都必须显式落到上述矩阵中的某个 outcome，禁止通过默认转成 raw prompt 的方式旁路 ingress。
- `transcript write` 只对 ingress 明确定义为 transcript-visible 的 normalized messages 成立，replay output 不得隐式写回 transcript。

End-to-end sequences for the first implementation slice:

Admitted turn:

```text
caller / host
  -> SessionController.submit(...)
  -> SessionIngressProcessor.process(event, session_snapshot, runtime_services)
  -> SessionIngressResult(admission=admit_turn, normalized_messages, prompt_updates, private_updates)
  -> SessionController appends normalized transcript messages
  -> SessionController merges ingress prompt/private updates into turn-start inputs
  -> TurnEngine.prepare_request(...)
  -> sidecars contribute prompt/private fragments
  -> ContextAssembler builds prompt from PromptContextEnvelope only
  -> ModelRequest emits with separate RuntimePrivateContext
  -> host replay / stream events
  -> transcript continues with assistant/tool results
```

Local-only outcome:

```text
caller / host
  -> SessionController.submit(...)
  -> SessionIngressProcessor.process(event, session_snapshot, runtime_services)
  -> SessionIngressResult(admission=local_only or replay_only, replay_outputs, optional private_updates)
  -> SessionController applies local/session effects
  -> SessionController replays ingress-defined host output
  -> optional transcript write only if ingress emitted transcript-visible normalized messages
  -> no TurnEngine execution
  -> no model request emission
```

### 2. 将上下文拆成 `PromptContextEnvelope` 与 `RuntimePrivateContext`

后续 request build 不再向 `ContextAssembler` 直接传一个宽泛的 `runtime_context` bag，而是分成两类输入：

- `PromptContextEnvelope`: 允许进入 system prompt 或 model-visible turn context 的字段
- `RuntimePrivateContext`: 仅供 runtime、tool execution、policy projection、diagnostics 和 host bridge 使用的私有字段

其中：

- `PromptContextEnvelope` 采用强类型外壳，至少包含：
  - `memory_fragments`
  - `hook_fragments`
  - `compaction_fragments`
  - `attachments`
  - `session_hints`
  - `extensions`
- `RuntimePrivateContext` 采用强类型外壳，至少包含：
  - `permission_context`
  - `policy_state`
  - `run_id`
  - `parent_run_id`
  - `requested_model_route`
  - `resolved_model_route`
  - `invocation_mode`
  - `diagnostics`
  - `extensions`

这里采用“强外壳 + 弱扩展”模式，而不是纯 `dict` 或一次性全量强类型化。

同时收紧 carrier 责任：

- `ContextAssembler` 只消费 `PromptContextEnvelope`
- `TurnContext` 变成 prompt-safe carrier，不再承载 authoritative private context
- `ToolContext` 与 request metadata 承载 `RuntimePrivateContext`
- `ModelRequest` 补 private context carrier 或等价字段，用于 provider/model-runtime 边界外的私有执行元数据

Why:

- 当前的“黑名单式隐藏少数字段”过于脆弱，新增私有字段时极易再次泄露到 prompt。
- 明确双通道后，memory/hooks/host sidecars 可以分别贡献 prompt-visible 和 private-only 信息，不再依赖“先写进 runtime_context，再希望 assembler 不要展示它”。

Alternatives considered:

- 保留单一 `runtime_context`，只扩大 `_PROMPT_HIDDEN_RUNTIME_CONTEXT_KEYS`。拒绝，因为这依赖持续维护黑名单，边界本质上仍然不存在。
- private context 第一阶段继续完全使用 `dict`。拒绝，因为这会把新的边界再次退化成约定而不是 contract。

Merge precedence for the first implementation slice:

1. session/base context
2. ingress updates
3. sidecar contributions
4. request-scoped explicit overrides, if the caller path already supports them

Detailed merge rules:

- `PromptContextEnvelope` 中的 fragment lists 采用稳定追加顺序：session/base -> ingress -> sidecar -> explicit override。
- `RuntimePrivateContext` 中的 scalar/object fields 在 key 冲突时由后阶段覆盖前阶段，但不得通过 `None` 或空值隐式清空已有必需字段，除非调用方显式声明 reset 语义。
- `diagnostics` 是附加型信息，不允许后阶段静默删除前阶段 diagnostics；如需聚合，应通过 append/merge，而不是 replace。
- `ContextAssembler` 只能看到最终合并后的 `PromptContextEnvelope`，不得在 prompt build 阶段回读 private carrier 再次做隐式拼接。

Ownership matrix for the first implementation slice:

| artifact | owner | primary writers | primary readers | persisted | prompt-visible |
| --- | --- | --- | --- | --- | --- |
| `PromptContextEnvelope` | turn/request preparation | ingress, sidecars, explicit request override | `ContextAssembler`, prompt fixtures | no | yes |
| `RuntimePrivateContext` | turn/runtime execution | session base state, ingress, sidecars, execution policy, route resolution | `TurnEngine`, `ToolContext`, `ModelRequest`, host diagnostics | no | no |
| transcript messages | `SessionController` | ingress-normalized messages, turn continuation events | session resume path, host transcript readers | yes | partially, via transcript semantics |
| `IngressReplayOutput` | ingress + session control surface | `SessionIngressProcessor` | host replay bridge, session control | no | host-visible only |
| managed session registry | `BoundHostRuntime` | one-shot helpers, bound host session creation/close paths | host shutdown path | no | no |
| session metadata / memory artifact | `SessionController` | session lifecycle, memory/background consolidation | session cleanup, diagnostics, resume path | yes | no by default |

### 3. 采用双通道 sidecar 贡献协议，而不是让 sidecar 直接改 prompt

memory、hooks、compaction 及后续 host/control-plane sidecar 统一通过结构化贡献协议参与 request preparation，而不是直接修改 prompt 拼接输入。

建议的统一语义是 sidecar 返回：

- `prompt_fragments`
- `private_updates`
- `diagnostics`

这样 `TurnEngine` 在 join sidecar 结果时可以：

- 把 `prompt_fragments` 注入 `PromptContextEnvelope`
- 把 `private_updates` 合并到 `RuntimePrivateContext`
- 把 `diagnostics` 留给 request metadata / host events / tests

Why:

- sidecar 贡献协议一旦统一，`ContextAssembler` 只负责 prompt 装配，`TurnEngine` 只负责汇总，不需要知道每个服务的特殊字段。
- 也能减少目前 sidecar 通过共享 dict 改写 `runtime_context` 的隐式行为。

Alternatives considered:

- 继续允许 sidecar 原地 mutate `runtime_context`。拒绝，因为这会让上下文边界继续隐式化。

### 4. lifecycle ownership 重新分配到三层

新的 owner 模型如下：

- `BoundHostRuntime` / host binding scope: 拥有 `host.startup() / ready() / shutdown()`，负责 host 生命周期
- `SessionController`: 拥有 session start/end、transcript、session memory artifact、session hook payload、background memory consolidation，且 `close()` 必须幂等
- `RuntimeAssembly.run_prompt()/stream_prompt()`: 作为 one-shot helper，只保证 session create/resume/start/submit/drain/close 的完整性，不再成为 host lifecycle owner

并且这轮直接把 `BoundHostRuntime` 做成 async context manager：

- `__aenter__()` 负责 `host.startup()` 与 `host.ready()`
- `__aexit__()` 负责关闭仍存活的 managed sessions 后再执行 `host.shutdown()`
- `BoundHostRuntime` 维护 helper-owned / bound-owned session registry

这意味着：

- `SessionController.start()/close()` 不再直接调用 host startup/shutdown
- long-lived session 可以在同一个 bound host 生命周期下复用
- one-shot helper 必须在 `finally` 中调用 `session.close()`
- host shutdown ordering 统一为：close managed sessions -> session end cleanup -> host shutdown
- 显式 `startup()/ready()/shutdown()` 路径与 async context-manager 路径必须保持语义等价，只是 ownership surface 不同
- `__aexit__()` 或显式 shutdown 遇到 session close 失败时，必须 best-effort 继续关闭剩余 managed sessions，汇总 diagnostics，并在完成 cleanup 后再决定是否上抛 terminal failure

Why:

- startup/shutdown 属于 host bridge concern，不应该跟每个 session 的开关绑定。
- session close 是 session resource concern，必须由 session 或 helper 保证，而不是寄希望于调用方记得手工善后。

Alternatives considered:

- 保留当前 `SessionController` 内置 host lifecycle。拒绝，因为这会让 session 和 host 生命周期发生重复 owner。
- 把 session close 也交给 host bridge。拒绝，因为 transcript、session memory artifact 和 session hooks 仍然是 runtime/session concern。

### 5. 以兼容迁移方式收紧 helper 与 contract

现有 public-ish surface 保持尽量稳定，但语义收紧：

- `InboundEvent` surface 可以保留，内部改为先走 ingress processor
- `TurnContext.metadata` / `ToolContext.metadata` 可以继续存在，但其 authoritative private payload 必须收敛到 `RuntimePrivateContext`，prompt-visible 部分必须经 `PromptContextEnvelope` 白名单进入 prompt
- `RuntimeAssembly.run_prompt()/stream_prompt()` 继续保留，但文档和行为改为 one-shot session helper，并保证 `close()`
- `BoundHostRuntime` 继续保留显式 lifecycle surface，但新增 async context-manager 用法作为推荐 host-scope 模式

同时通过 protocol/conformance tests 锁住：

- admitted prompt 在首个 model request 前进入 transcript
- prompt 中不再出现 private policy/permission/diagnostic 字段
- one-shot helper 在 success / error / interrupt 下都执行 session close

Why:

- 这批改动涉及 session、turn、host 和 tests，必须允许过渡期兼容，否则容易在多个面同时破坏现有 harness。

Alternatives considered:

- 一次性删除现有 helper 和 metadata carrier。拒绝，因为迁移面过大，回归风险高。

## Risks / Trade-offs

- [更多中间模型] ingress result 和双上下文 envelope 会增加运行时对象数量。 → Mitigation: 第一阶段只引入最小必要字段，禁止让这些模型演化成新的 metadata junk drawer。
- [迁移期间双路径并存] 老的 `runtime_context` 习惯和新的 prompt/private split 可能暂时共存。 → Mitigation: 用单向适配器把旧字段收敛到新 envelope / private context，禁止新代码继续直接扩散原始 `runtime_context`。
- [host 调用者误解 lifecycle] 把 host lifecycle 移出 session 后，调用方可能误以为 one-shot helper 也负责 shutdown host。 → Mitigation: 明确 helper 仅保证 session close，并在 bound host surface 上保留显式 startup/ready/shutdown。
- [host scope 泄漏] `BoundHostRuntime` 持有 session registry 后，如果退出路径不完整，可能遗留未关闭 session。 → Mitigation: 将 managed-session close 纳入 `__aexit__()` 的强制行为，并用 tests 锁住退出顺序。
- [测试基线变动] prompt 内容、host lifecycle 顺序和 session close 时机会导致 golden 更新。 → Mitigation: 只锁边界语义，不锁无关时序细节或内部临时字段。

## Migration Plan

1. 新增 `SessionIngressProcessor` / `SessionIngressResult`，让 `SessionController` 先消费 ingress 结果再决定 transcript mutation 和 turn admission。
2. 引入 prompt/private context envelope，修改 `TurnEngine` 与 `ContextAssembler`，停止把 private control-plane metadata 直接拼入 system prompt。
3. 将 host lifecycle 调用从 `SessionController` 中移除，改由 bound host scope 持有；同时让 one-shot helper 在 `finally` 中执行 `session.close()`。
4. 更新 memory/hooks/compaction 等 sidecar 贡献协议，以及相关 `TurnContext` / `ToolContext` / `ModelRequest` carrier。
5. 为 `BoundHostRuntime` 增加 async context-manager 和 session registry，并统一 shutdown ordering。
6. 补齐 protocol/conformance tests、session tests 和 host bridge tests，覆盖 ingress、context boundary 与 lifecycle 语义。
7. 以 compat-shim removal gate 检查 legacy `runtime_context` 读写是否已清退到允许范围内，再决定是否移除兼容层。

Rollback strategy:

- 若 ingress 或 context split 迁移受阻，可保留兼容适配层，把旧调用收敛到新模型，而不是回滚到继续扩散原始 `runtime_context`。
- 若 lifecycle owner 调整导致 host 集成受阻，可暂时保留 helper 级兼容包装，但不得恢复 `SessionController` 直接拥有 host startup/shutdown。

Compat-shim removal gate:

- 只有当 legacy `runtime_context` 的 authoritative writes 已经清零，compat shim 只剩只读桥接语义时，才允许计划删除 compat 层。
- `TurnEngine`、`SessionController`、memory/hooks/compaction、agent/skill execution 与 host bridge 的 request path 必须都切到 `PromptContextEnvelope` / `RuntimePrivateContext`，才能开始删除共享 metadata bag 的旧入口。
- request-level fixtures、host bridge tests 与 conformance matrix 必须证明 private state 不再依赖 prompt-facing metadata bag 暴露。
- 若仍存在 service handle、policy object 或 permission object 借道 legacy metadata 传播，则 compat shim removal gate 视为未通过。

## Contract Appendix

### Session ingress contract

第一阶段固定最小 ingress contract：

- `IngressAdmission`
  - `kind`
  - `reason`
  - `metadata`
- `IngressReplayOutput`
  - `kind`
  - `payload`
  - `visible_to_host`
- `SessionIngressResult`
  - `normalized_messages`
  - `replay_outputs`
  - `prompt_updates`
  - `private_updates`
  - `admission`

### Context carrier contract

第一阶段固定双 carrier contract：

- `PromptContextEnvelope`
  - `memory_fragments`
  - `hook_fragments`
  - `compaction_fragments`
  - `attachments`
  - `session_hints`
  - `extensions`
- `RuntimePrivateContext`
  - `permission_context`
  - `policy_state`
  - `run_id`
  - `parent_run_id`
  - `query_source`
  - `requested_model_route`
  - `resolved_model_route`
  - `invocation_mode`
  - `diagnostics`
  - `extensions`

### Legacy `runtime_context` migration appendix

第一阶段不要求一次性删除所有 `runtime_context` 读取点，但要求它们单向收敛到新 contract。当前已知高频字段的迁移目标如下：

| legacy key | new carrier / field | authoritative owner | compat shim allowed | target stage |
| --- | --- | --- | --- | --- |
| `permission_context` | `RuntimePrivateContext.permission_context` | execution policy / turn runtime | yes | Slice C-D |
| `execution_policy_state` | `RuntimePrivateContext.policy_state` | execution policy | yes | Slice C-D |
| `run_id` | `RuntimePrivateContext.run_id` | agent execution / turn runtime | yes | Slice C-D |
| `parent_run_id` | `RuntimePrivateContext.parent_run_id` | agent execution | yes | Slice C-D |
| `query_source` / `command_type` / `agent_name` | `RuntimePrivateContext.query_source` or ingress classification metadata | ingress + turn runtime | yes | Slice A-D |
| `requested_model_route` | `RuntimePrivateContext.requested_model_route` | agent execution / route resolver | yes | Slice C-D |
| `resolved_model_route` | `RuntimePrivateContext.resolved_model_route` | route resolver / turn runtime | yes | Slice C-D |
| `invocation_mode` | `RuntimePrivateContext.invocation_mode` | turn runtime | yes | Slice C-D |
| `memory_retrieval` | `PromptContextEnvelope.memory_fragments` plus `RuntimePrivateContext.diagnostics.retrieval` | memory service | temporary only | Slice E |
| `memory_diagnostics` | `RuntimePrivateContext.diagnostics` | memory service / session runtime | temporary only | Slice E |
| `host_runtime` / `hook_bus` style service references | runtime-private service handles, not prompt carriers | bound host / runtime services | no new usage | Slice H cleanup |

Migration rules:

- 允许旧调用点从 compat shim 读取 legacy keys，但新代码不得再向共享 `runtime_context` 写入新的 authoritative 字段。
- prompt-visible 数据必须优先落到 `PromptContextEnvelope`，而不是先写 legacy key 再由 assembler 过滤。
- service handles、policy objects、permission objects 这类私有对象不得再借道 prompt-facing metadata carrier 传播。

### Host-scope lifecycle contract

第一阶段固定 host-scope contract：

- `BoundHostRuntime.__aenter__()`:
  - `host.startup()`
  - `host.ready()`
- `BoundHostRuntime.__aexit__()`:
  - close managed sessions
  - ensure session end cleanup completes
  - `host.shutdown()`
- explicit lifecycle path:
  - `host.startup()`
  - `host.ready()`
  - run one or more sessions
  - `host.shutdown()`
  - semantic outcome MUST match context-managed path
- failure handling:
  - close failure of one managed session MUST NOT skip cleanup attempts for the remaining sessions
  - runtime MUST aggregate diagnostics for failed session cleanup
  - runtime MUST attempt host shutdown after managed-session cleanup attempts complete
  - terminal failure MAY be re-raised after cleanup, but only after shutdown semantics are resolved
- managed session registry:
  - helper-owned sessions MUST register on create
  - helper-owned sessions MUST deregister on close
  - exit path MUST close any remaining registered sessions
