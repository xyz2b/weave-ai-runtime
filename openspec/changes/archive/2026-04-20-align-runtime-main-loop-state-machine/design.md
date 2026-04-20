## Context

当前 runtime 的核心执行链路已经是：

```text
RuntimeKernel -> SessionController -> TurnEngine -> Tool/Agent/Skill runtimes
```

就 Runtime 主循环而言，现状已经具备几个正确方向：

- `SessionController.stream_until_idle()` 是 session 级 async generator，负责命令队列、transcript 写入、resume 和 session 级 memory 持久化。
- `TurnEngine._run_turn_stream_impl()` 是 turn 级流式迭代循环，负责 request preparation、model stream、tool replay 和 terminal 事件。
- `StreamingToolOrchestrator` 已经把 tool lifecycle、并发 lane、ordered replay 和 context updates 拆成独立子组件，而不是继续把所有逻辑塞在 turn loop 里。
- compaction、memory、hooks、permissions 已经被放到 `RuntimeServices` 控制面，而不是简单 callback。

但和参考实现式 runtime-first 主循环相比，仍有四个关键缺口：

1. turn 状态是隐式的。真正决定 continuation 的状态分散在 `SessionState.metadata`、`TurnEngine` 的局部变量和 event metadata 里，没有显式 `TurnLoopState` / `Transition` contract。
2. pre-turn 控制面准备仍是串行 join。memory retrieval 和 hook context 虽然都在 request 前进入主循环，但没有 sidecar supervisor，也没有失效重跑语义。
3. stop / recovery 语义分裂。`Stop` hook 在 `TurnEngine`，memory persistence 和 session refresh 在 `SessionController`，compaction hooks 已声明却未真正进入主循环，预算/恢复路径也尚未统一。
4. 缺少 budget/recovery 控制面。当前记录了 usage、abort、blocked 等终态，但没有把 `max_tokens`、tool-result 膨胀、reactive compaction、provider fallback 等恢复路径收敛成标准 continuation action。

这个 change 的目标不是复制参考实现的 monolithic `query.ts`，而是在保留当前模块化分层优势的前提下，把 Runtime 主循环补成显式状态机 contract。更具体地说，本 change 会把“async generator 驱动的事件流”钉为主循环的规范表面，并把上下文、工具、记忆、预算、恢复和状态转移收敛为 runtime 自己拥有的控制面职责。

## Goals / Non-Goals

**Goals:**

- 保留 `SessionController` 和 `TurnEngine` 的两层状态机结构，并把二者职责边界明确化。
- 把 async generator event stream 固定为 Runtime 主循环的 canonical surface，而不是可选包装层。
- 引入显式的 turn-phase、transition reason 和 recovery action contract。
- 把 memory / hooks / compaction 等 pre-turn control-plane 工作升级为可监督的 sidecar orchestration，而不是顺序拼接。
- 把 stop handling、post-turn effects、session integration 和 budget/recovery 接入统一的主循环语义。
- 明确由 runtime 统一拥有 turn-scoped 的上下文装配、工具编排、记忆 sidecar、预算、恢复和状态转移决策。
- 保持 `StreamingToolOrchestrator`、compaction manager 和 memory manager 作为专门子系统，而不是重新塞回一个巨型 query engine。

**Non-Goals:**

- 不把现有 runtime 重写成参考实现风格的单文件大循环。
- 不在本 change 中重写 memory retrieval 算法、compaction summary 算法或 tool orchestration 语义。
- 不改变现有 host/kernel 分层，也不把 session-scoped 文件持久化职责全部下沉到 `TurnEngine`。
- 不要求第一版实现每一种参考实现内部恢复策略，只要求建立统一 contract 和最关键的恢复入口。

## Immediate Guardrails

- 这是一个兼容性迁移，不只是内部重构。host-facing `TERMINAL` 收紧为 turn-final only 后，旧的 `TERMINAL(stop_reason=tool_use)` 消费方必须与 engine、controller、golden tests、host adapter 在同一批一起迁移，不能让新旧判断路径长期并存。
- 兼容期可以临时镜像旧字段，但这些字段只能作为 debug/transition aid，不能重新成为 session projection、child-run projection 或 helper 聚合的 authoritative 输入。
- 第一阶段的 budget/recovery 范围刻意收窄，只要求统一 `max_tokens` / 输出预算、tool-result budget 和 reactive compaction 三类恢复入口；provider retry/fallback 明确后置，不纳入本 change 的最小验收面。

## Decisions

### 1. 保留两层状态机，但把 turn loop 显式建模

runtime 继续保留：

- `SessionController`: session command queue、transcript 持久化、resume、session memory artifacts
- `TurnEngine`: 单个 turn 内部的 streaming continuation loop

同时明确：

- `SessionController.stream_until_idle()` 是 session-level canonical async-generator surface
- `TurnEngine.run_turn_stream()` 是 turn-level canonical async-generator surface
- `run_until_idle()` / `run_turn()` 之类聚合 helper 只能建立在上述 event stream 之上，而不能绕开主循环 contract

但 `TurnEngine` 内部将新增显式 turn-loop models，例如：

- `TurnPhase`
- `TurnTransitionReason`
- `TurnRecoveryAction`
- `TurnLoopState`
- `TurnOutcomePlan` / `TurnPostEffects`

Why:

- 当前分层本身是优点，不需要为了“像参考实现”而退回单个 `query.ts` 巨型状态对象。
- 真正缺的是“显式状态 contract”，不是“更多内联代码”。
- 这样能让 tests 和 host 观察到连续性的原因，而不是只能通过 transcript 反推。
- 这样也能把“主循环是 async generator 事件流”从实现细节提升为稳定接口约束。

Alternatives considered:

- 把 `SessionController` 和 `TurnEngine` 合并成单一 query engine。拒绝，因为这会损失当前更好的模块边界。
- 继续把状态放在局部变量和 `metadata` bag 里。拒绝，因为 budget/recovery 和 sidecar invalidation 会继续隐式化。

### 2. runtime 明确拥有 turn-scoped orchestration，而不是 provider/host 拥有

runtime 将统一拥有并协调以下 turn-scoped 职责：

- 上下文装配和 request shaping
- tool observation、resolution、replay 和 ordered continuation
- memory / hook / compaction sidecar 的 join、失效和重跑
- budget / recovery policy
- transition reason 和终态投影

provider adapter 只负责 provider raw stream / completion contract；host 只负责消费 turn event stream；工具子系统只负责在 runtime 给定的 contract 下执行。

Why:

- 参考实现风格 runtime 的关键不是“模型自己决定一切”，而是 runtime 接管横切控制面。
- 如果这些职责继续散落给 provider、host 或局部子系统，显式状态机就会再次退化成隐式流程。

Alternatives considered:

- 让 provider adapter 直接处理 stop-reason recovery。拒绝，因为恢复应当是 runtime continuation policy。
- 让 host 自己组装 memory/tool/budget 逻辑。拒绝，因为那会破坏 host-independent runtime contract。

### 3. 将主循环固定为 phase-based contract，而不是 if/return 拼接流程

turn loop 逻辑将显式收敛为一组稳定 phase：

1. `prepare`
2. `prefetch_sidecars`
3. `compact_or_rebuild`
4. `build_request`
5. `stream_attempt`
6. `replay_tools`
7. `stop_phase`
8. `recovery_decision`
9. `advance_or_finish`
10. `terminal`

这里的目标不是把代码写成教科书状态机框架，而是保证每个 cross-cutting concern 都有稳定 join point。

Why:

- 参考实现风格 runtime 的关键不在 Thought/Action，而在“哪一类控制面逻辑挂在哪个 join point 上”。
- phase 明确后，`PreCompact` / `PostCompact`、budget guard、stop hooks、session effects 才有稳定挂点。

Alternatives considered:

- 保持现有局部变量流转，只做少量注释。拒绝，因为这不足以承接新的恢复和 sidecar 语义。

### 3A. 明确定义 `TurnLoopState`，而不是继续依赖局部变量和 metadata bag

从参考实现在 [query.ts](/Users/xyzjiao/AIProject/AIAgentRuntime/cc-src/query.ts#L203) 中显式维护的 `State`，我们的 turn loop 也必须有一个 loop-carried state，只是保持当前 Python runtime 的模块化拆分，而不是复制单文件巨型对象。规范上，`TurnLoopState` 至少包含：

- `phase`: 当前 `TurnPhase`
- `iteration`: 当前 continuation 序号，对应参考实现的 `turnCount`
- `working_messages`: 当前 iteration 的工作消息视图，对应参考实现的 `messages`
- `policy_state`: 当前 execution/tool/skill policy 快照
- `tool_runtime`: 当前 tool context、selected executor、pending replay plan，对应参考实现的 `toolUseContext`
- `sidecars`: memory / hooks / invocation warmup 的 supervisor 句柄、generation id、join 结果
- `compaction`: 最近一次 compact/collapse 的输入快照、结果摘要、continuation metadata
- `recovery`: `max_output_tokens_recovery_count`、`has_attempted_reactive_compact`、`max_output_tokens_override` 等恢复控制位
- `post_effects`: stop phase 产出的结构化后处理结果
- `transition`: 上一次 continuation 的 `TurnTransition`
- `terminal`: 当前 turn 的 `TurnTerminal`，仅在进入 `terminal` 时存在

这里的意图和参考实现一致：不是为了“保存更多临时变量”，而是为了把 continuation 为什么发生、哪些 sidecar 已失效、恢复是否已经尝试过，变成 runtime 能显式推理和测试的事实。

### 3B. 将 phase 定义成正式状态，而不是松散“步骤列表”

各个 `TurnPhase` 的定义如下：

| State | Responsibility | Legal exits |
| --- | --- | --- |
| `prepare` | 固化本次 iteration 的输入快照，继承上一轮 `transition`，建立新的 sidecar generation | `prefetch_sidecars` |
| `prefetch_sidecars` | 启动 memory / hook / invocation 等 control-plane sidecar，不要求在此处全部阻塞等待 | `compact_or_rebuild` |
| `compact_or_rebuild` | join 必须参与 request shaping 的 sidecar，执行 tool-result budget、collapse、auto/reactive compact、continuation rebuild | `build_request`、`recovery_decision` |
| `build_request` | 解析 model capabilities、executor、request metadata，并发出 `REQUEST_START` | `stream_attempt` |
| `stream_attempt` | 消费 model stream，边流边观察 tool use，并在支持时提前启动 streaming tool execution | `replay_tools`、`stop_phase`、`recovery_decision` |
| `replay_tools` | 收敛 tool executor 结果、tool context 更新、attachment/tool_result 回填 | `recovery_decision` |
| `stop_phase` | 执行 stop hooks、诊断收集、memory extraction intent、turn post-effects 生成 | `recovery_decision` |
| `recovery_decision` | 依据 provider terminal、budget policy、compaction policy、stop outcome 选择恢复动作或终止 | `compact_or_rebuild`、`build_request`、`advance_or_finish` |
| `advance_or_finish` | 提交 `TurnTransition` 或 `TurnTerminal`，更新 `TurnLoopState` 并决定是否进入下一 iteration | `prepare`、`terminal` |
| `terminal` | 发出 turn terminal event 并结束 turn async generator | 无 |

这套 phase 划分直接吸收参考实现在 [query.ts](/Users/xyzjiao/AIProject/AIAgentRuntime/cc-src/query.ts#L369)、[query.ts](/Users/xyzjiao/AIProject/AIAgentRuntime/cc-src/query.ts#L560)、[query.ts](/Users/xyzjiao/AIProject/AIAgentRuntime/cc-src/query.ts#L1267) 上的 join-point 设计，但避免把所有逻辑都重新塞回一个 `query.ts`。

### 3C. 明确定义合法状态流转

turn loop 的合法流转如下：

| From | Guard / event | Action | To |
| --- | --- | --- | --- |
| `prepare` | iteration 初始化完成 | 启动新一代 sidecar supervisor | `prefetch_sidecars` |
| `prefetch_sidecars` | sidecar 已启动，进入 request-shaping 边界 | 携带 sidecar 句柄前进 | `compact_or_rebuild` |
| `compact_or_rebuild` | 上下文可直接发请求 | 提交 compact/collapse 结果，生成 request 输入 | `build_request` |
| `compact_or_rebuild` | compaction / collapse 触发恢复 | 记录 `TurnRecoveryAction` | `recovery_decision` |
| `build_request` | request 已发出 | 发出 `REQUEST_START` 事件 | `stream_attempt` |
| `stream_attempt` | assistant attempt 结束且存在可执行 tool uses | 固化 assistant message 与 tool batch | `replay_tools` |
| `stream_attempt` | assistant attempt 结束且无 tool uses | 固化 assistant message | `stop_phase` |
| `stream_attempt` | provider error / abort / withheld terminal 需要恢复或停机 | 记录终态候选与恢复候选 | `recovery_decision` |
| `replay_tools` | tool batch 已回填 | 写入 tool_result / attachment / context update | `recovery_decision` |
| `stop_phase` | stop hooks 与 post-effects 已完成 | 写入 stop outcome | `recovery_decision` |
| `recovery_decision` | 选择 `compact_and_retry` 或 `rebuild_request` | 丢弃过期 sidecar 结果，保留必要 recovery bits | `compact_or_rebuild` |
| `recovery_decision` | 选择 `retry_with_override` | 保留 working context，仅更新 request override | `build_request` |
| `recovery_decision` | 选择 `continue_same_turn` | 组装 continuation message / tool results | `advance_or_finish` |
| `recovery_decision` | 选择 `halt` | 组装终态 | `advance_or_finish` |
| `advance_or_finish` | 形成新的 `TurnTransition` | 更新 `TurnLoopState.transition` 与 `iteration += 1` | `prepare` |
| `advance_or_finish` | 形成 `TurnTerminal` | 写入 terminal payload | `terminal` |

禁止的事情也要明确：

- 任何 phase 都不能直接递归调用 turn loop；只能通过 `advance_or_finish -> prepare` 重入。
- `stream_attempt` 不能跳过 `replay_tools` 直接把 tool results 伪装成下一条用户命令。
- `stop_phase` 不能直接把 session 置为 `WAITING`；它只能产出 turn terminal 或 transition，session 投影由外层 controller 负责。

### 3D. continuation reason 与 recovery action 必须是显式枚举参考实现在 [query.ts](/Users/xyzjiao/AIProject/AIAgentRuntime/cc-src/query.ts#L1110)、[query.ts](/Users/xyzjiao/AIProject/AIAgentRuntime/cc-src/query.ts#L1162)、[query.ts](/Users/xyzjiao/AIProject/AIAgentRuntime/cc-src/query.ts#L1217)、[query.ts](/Users/xyzjiao/AIProject/AIAgentRuntime/cc-src/query.ts#L1246)、[query.ts](/Users/xyzjiao/AIProject/AIAgentRuntime/cc-src/query.ts#L1302)、[query.ts](/Users/xyzjiao/AIProject/AIAgentRuntime/cc-src/query.ts#L1338)、[query.ts](/Users/xyzjiao/AIProject/AIAgentRuntime/cc-src/query.ts#L1725) 中把 continuation 原因显式写进 `state.transition.reason`。我们的设计也要做到这一点。

`TurnRecoveryAction` 统一限制为：

- `continue_same_turn`
- `rebuild_request`
- `compact_and_retry`
- `retry_with_override`
- `halt`

第一阶段要求支持的 `TurnTransitionReason` 至少包括：

| Transition reason | Typical trigger | Recovery action | Destination |
| --- | --- | --- | --- |
| `next_turn` | tool replay 或 attachment 注入后需要继续同一 turn | `continue_same_turn` | `prepare` |
| `collapse_drain_retry` | prompt-too-long 先尝试 drain collapse 队列 | `rebuild_request` | `compact_or_rebuild` |
| `reactive_compact_retry` | prompt-too-long / media overflow 触发 reactive compact | `compact_and_retry` | `compact_or_rebuild` |
| `max_output_tokens_escalate` | 首次命中输出上限且允许抬高 output cap | `retry_with_override` | `build_request` |
| `max_output_tokens_recovery` | 输出被截断，需要 runtime 注入 continuation nudge | `continue_same_turn` | `prepare` |
| `stop_hook_blocking` | stop hooks 注入 blocking diagnostics 或 policy feedback | `continue_same_turn` | `prepare` |
| `token_budget_continuation` | token budget 要求继续但缩小工作面 | `continue_same_turn` | `prepare` |

这里保留了参考实现中最关键的 continuation reason，但不照搬它的内部对象结构。我们的目标是让 host、tests 和 diagnostics 明确知道“为什么继续”，而不是从 transcript 猜。

### 3E. attempt terminal 与 turn terminal 必须严格分离

当前实现里最危险的歧义之一，是 provider 一次请求结束时的结果和整个 turn 结束时的结果被混用为同一个 `TERMINAL` 概念。这里必须收紧：

- `AttemptTerminal` 表示单次 provider request / assistant attempt 的结束
- `TurnTerminal` 表示整个 turn async generator 的最终结束
- host-facing 的 `TERMINAL` 事件名必须保留给 `TurnTerminal`
- provider attempt 的结束若需要暴露，必须通过新的 `ATTEMPT_FINISHED` 事件或等价 metadata 暴露，但绝不能冒充 turn final

这意味着：

- assistant 输出 `tool_use` 后，该次 model attempt 可以结束，但 turn 仍处于 `replay_tools -> recovery_decision -> advance_or_finish` 路径中
- 命中 `max_turns`、`error`、`interrupted`、`blocked` 时，turn loop 必须再发出唯一一次 `TurnTerminal`
- 任何 turn stream 都必须满足“零个或多个 attempt-finished，恰好一个 turn-terminal，且 turn-terminal 之后不再有其他 turn event”

Why:

- 只有这样，session controller、child-run store、host UI 才不会把“本次请求结束”误判成“本个 turn 结束”。
- 这也是参考实现虽然内部有多次 continuation，但外部仍然是单个 query terminal 的关键语义。

第一阶段的实现落点必须直接对应到 [engine.py](/Users/xyzjiao/AIProject/AIAgentRuntime/src/runtime/turn_engine/engine.py)：

- [engine.py](/Users/xyzjiao/AIProject/AIAgentRuntime/src/runtime/turn_engine/engine.py) 中当前 host-facing `TurnStreamEventType.TERMINAL` 的语义必须改成“仅 turn-final”
- [engine.py](/Users/xyzjiao/AIProject/AIAgentRuntime/src/runtime/turn_engine/engine.py) 中当前用 `TERMINAL(stop_reason=\"tool_use\")` 表示 attempt 结束的做法必须移除
- [engine.py](/Users/xyzjiao/AIProject/AIAgentRuntime/src/runtime/turn_engine/engine.py) 必须保证 `max_turns`、`error`、`interrupted`、`blocked` 都走显式 final terminal 出口
- [engine.py](/Users/xyzjiao/AIProject/AIAgentRuntime/src/runtime/turn_engine/engine.py) 必须保证 final terminal 之后不再产出任何 turn event

### 3F. `ATTEMPT_FINISHED` contract 必须写死，避免重新退回旧 `TERMINAL`

既然 attempt outcome 不再复用 host-facing `TERMINAL`，那就必须把新的 attempt-level contract 直接定义清楚。第一阶段建议固定为 `ATTEMPT_FINISHED` 事件；如果实现上最终选择 metadata carrier，也必须承载同样的信息模型。

`AttemptFinished` 至少包含：

- `iteration`: 本次 attempt 所属的 turn iteration
- `request_id`: provider request 标识
- `attempt_stop_reason`: 本次 attempt 的 provider 级 stop reason，例如 `tool_use`、`end_turn`、`error`
- `usage`: 本次 attempt 的 usage 快照
- `error`: provider/model error 文本，若存在
- `abort_reason`: runtime 或 host 注入的 abort 原因，若存在
- `produced_tool_calls`: 本次 attempt 是否产出了可执行 tool uses，以及对应计数或摘要
- `metadata`: provider/raw terminal 的其余调试字段

并且要明确：

- `ATTEMPT_FINISHED` 只能描述“这一次 request 发生了什么”
- `ATTEMPT_FINISHED` 不能暗示 turn 已经结束
- `TurnResult.attempts` 的每一项都必须来源于这个 attempt-level contract，而不是复用 turn-final payload

Why:

- 如果 attempt-level payload 不固定，后续实现最容易走回“沿用旧 `TERMINAL` 字段”的老路。
- 这也是让 `run_turn_stream()` 和 `run_turn()` 保持一致语义的最低前提。

### 4. pre-turn sidecar 采用 supervisor 模式，支持 join / cancel / restart

memory retrieval、hook context、invocation warmup 等 pre-turn 工作将通过统一 sidecar supervisor 管理。第一版至少要求：

- sidecar 可以在 provider request 前并发启动
- request 发出前必须在确定 join point 收敛
- 若 compaction 或 recovery 使 sidecar 输入失效，旧结果必须被取消或丢弃，并允许重跑

这里不会强制所有 sidecar 都并发，只定义一套统一 contract，让可并发的 control-plane 工作不再默认串行。

Why:

- 参考实现的 relevant memory prefetch 本质上是 runtime sidecar，不是另一个 workflow。
- 当前 `memory.collect()` 和 `hooks.collect()` 虽然已经进了主循环，但仍是“顺序 await”，没有 sidecar 价值。

Alternatives considered:

- 继续顺序 `await collect()`。拒绝，因为 latency 和 invalidation 语义都会越来越差。
- 让每个 service 自己偷偷开后台任务。拒绝，因为无法形成 deterministic join semantics。

### 5. stop phase 产出显式 `TurnPostEffects`，SessionController 只负责 session-scoped commit

`TurnEngine` 不直接接管 session 文件写入，但会在 stop phase 结束时产出结构化 post-turn effects，例如：

- turn diagnostics
- retrieval trace
- stop outcome
- recovery hint
- memory/session persistence suggestions
- background extraction trigger intent

`SessionController` 继续负责 transcript 和 session memory artifacts，但不再主要依赖“从 messages/metadata 推断发生了什么”，而是消费显式 turn outcome。

Why:

- 这能保留 control plane 与 session plane 的边界。
- 也能把目前分裂的 stop 语义重新收束成同一条主循环结果。

Alternatives considered:

- 把所有 stop 后处理都搬进 `TurnEngine`。拒绝，因为 session file layout、resume artifact 和 transcript store 仍然是 session concern。
- 保持当前 controller 从 transcript diff 推断 turn outcome。拒绝，因为这会让新的 recovery/budget 语义很难稳定。

### 5A. turn terminal reason 与 session status projection 必须显式定义参考实现在 [query.ts](/Users/xyzjiao/AIProject/AIAgentRuntime/cc-src/query.ts#L646)、[query.ts](/Users/xyzjiao/AIProject/AIAgentRuntime/cc-src/query.ts#L996)、[query.ts](/Users/xyzjiao/AIProject/AIAgentRuntime/cc-src/query.ts#L1051)、[query.ts](/Users/xyzjiao/AIProject/AIAgentRuntime/cc-src/query.ts#L1175)、[query.ts](/Users/xyzjiao/AIProject/AIAgentRuntime/cc-src/query.ts#L1264)、[query.ts](/Users/xyzjiao/AIProject/AIAgentRuntime/cc-src/query.ts#L1279)、[query.ts](/Users/xyzjiao/AIProject/AIAgentRuntime/cc-src/query.ts#L1515)、[query.ts](/Users/xyzjiao/AIProject/AIAgentRuntime/cc-src/query.ts#L1520)、[query.ts](/Users/xyzjiao/AIProject/AIAgentRuntime/cc-src/query.ts#L1711) 中把 turn terminal reason 写得很明确。我们的 runtime 也需要同样明确，但把 turn terminal 与 session status 投影拆开。

第一阶段要求支持的 `TurnTerminalReason` 至少包括：

- `completed`
- `blocking_limit`
- `prompt_too_long`
- `image_error`
- `model_error`
- `aborted_streaming`
- `aborted_tools`
- `stop_hook_prevented`
- `hook_stopped`
- `max_turns`

并且要增加两个强约束：

- 每个 turn 必须显式产出且只产出一个 `TurnTerminalReason`
- `completed: bool` 只能由 `TurnTerminalReason` 派生，不能反过来替代 terminal reason 做状态决策

建议的派生规则：

| Turn terminal reason | Derived `completed` |
| --- | --- |
| `completed` | `true` |
| `blocking_limit`、`prompt_too_long`、`image_error`、`model_error`、`aborted_streaming`、`aborted_tools`、`stop_hook_prevented`、`hook_stopped`、`max_turns` | `false` |

这些 turn terminal 会投影到 session 层状态机，规则如下：

| Turn terminal reason | Session projection | Controller action |
| --- | --- | --- |
| `completed` | `READY` | 提交 transcript / post-effects，继续消费命令队列 |
| `blocking_limit`、`stop_hook_prevented` | `WAITING` | 持久化 waiting 原因和 continuation metadata，停止继续 dequeue |
| `aborted_streaming`、`aborted_tools` | `INTERRUPTED` | 终止当前 drain，等待显式 resume |
| `prompt_too_long`、`image_error`、`model_error`、`hook_stopped`、`max_turns` | `READY` | 向 host 暴露 terminal diagnostics，但不把 session 标成 waiting |
| controller/runtime 自身故障，不属于正常 turn terminal | `FAILED` | 记录 fault 并停止 session |

`COMPLETED` / `STOPPED` 继续保留为 session 生命周期终态，而不是普通 turn 终态投影。这一点需要在文档里说清楚，否则 turn 完成和 session 结束会继续混淆。

### 5B. terminal precedence 必须明确，`error` 不能被改写成 `blocked`

当前实现最危险的误投影之一，是 provider/model error 经过 stop hook 或 waiting 逻辑后，被重新包装成 `blocked`。这在设计上必须显式禁止。

优先级规则必须固定为：

1. `model_error`、`aborted_streaming`、`aborted_tools`
2. `prompt_too_long`、`image_error`
3. `max_turns`
4. `stop_hook_prevented`、`blocking_limit`
5. `completed`

解释：

- 若 provider/model 已经失败，则 turn final 必须保留 failure 类 terminal，不得再降级成 waiting/blocking
- `stop_phase` 可以补充 diagnostics，但不能重写 failure 类 terminal 为 `blocked`
- 只有在 attempt 本身不是 failure 类 terminal 时，stop hook / policy gate 才有资格把 turn 投影到 `WAITING`

具体禁止规则：

- provider/model error 不能经 stop hook 改写成 `blocked`
- `aborted_*` 不能再被投影成 `WAITING`
- `max_turns` 不能被 fallback 成普通 `completed`
- `blocking_limit` 只能建立在非 failure attempt 之上

Why:

- 这直接决定 host 是提示“失败/中断”，还是提示“等待用户继续”，语义完全不同。
- 参考实现风格 runtime 的 recoverability 依赖于先保住真实终态，再决定是否下一轮 continuation。

### 5C. session / child-run 投影必须基于 terminal reason，而不是 `completed` 布尔值

当前实现里，child-run status 仍然可能从 `completed=False` 被粗暴推断成 `max_turns`。这在设计上必须明确禁止。

必须遵守：

- `SessionController` 只能根据 `TurnTerminalReason` 和必要的 terminal metadata 做 `READY / WAITING / INTERRUPTED / FAILED` 投影
- `AgentExecutionService` / child-run store 只能根据 `TurnTerminalReason` 做 `COMPLETED / MAX_TURNS / FAILED / DENIED` 等运行态投影
- `completed` 仅作为便利字段供上层快速判断“是否正常完成”，不能作为状态分类输入

最重要的几条禁止规则：

- 不能把所有 `completed=False` 统称为 `max_turns`
- 不能把 provider/model error 经 stop hook 改写后再投影成 `WAITING`
- 不能在未拿到显式 `TurnTerminalReason` 的情况下结束 child-run 记录

Why:

- 这类布尔投影会把完全不同的恢复路径和用户含义压扁到一个状态里，host 无法做出正确动作。
- 参考实现风格 runtime 的重点正是“终态原因显式化”，而不是让上层继续靠 heuristics 猜。

第一阶段的实现落点必须直接对应到 [agent_execution_service.py](/Users/xyzjiao/AIProject/AIAgentRuntime/src/runtime/agent_execution_service.py#L202)：

- [agent_execution_service.py](/Users/xyzjiao/AIProject/AIAgentRuntime/src/runtime/agent_execution_service.py#L202) 不能再使用 `turn_result.completed` 作为 child-run status 的主判断条件
- [agent_execution_service.py](/Users/xyzjiao/AIProject/AIAgentRuntime/src/runtime/agent_execution_service.py#L202) 必须改成读取显式 `TurnTerminalReason`
- 在保持现有 `AgentRunStatus` 枚举不扩展的前提下，最小正确映射应为：

| Turn terminal reason | Child-run projection |
| --- | --- |
| `completed` | `COMPLETED` |
| `max_turns` | `MAX_TURNS` |
| `model_error`、`aborted_streaming`、`aborted_tools`、`blocking_limit`、`stop_hook_prevented`、`hook_stopped`、`prompt_too_long`、`image_error` | `FAILED` |

如果后续需要把 `INTERRUPTED` / `BLOCKED` 单独升级成新的 `AgentRunStatus`，那是后续演进，不属于这一步的最小收敛范围。

### 5D. `TurnResult` contract 必须单独固定，不能继续混用 attempt / turn 语义

除了 event stream 之外，`run_turn()` 聚合返回的 `TurnResult` 也必须固定成明确 contract，否则上层还是会继续误用。

`TurnResult` 必须满足：

- `attempts[]`: 只保存 attempt-level outcome；每一项对应一次 `ATTEMPT_FINISHED`
- `stop_reason`: 只表示 turn-final terminal reason
- `completed`: 只等价于 `stop_reason == completed`
- `iterations`: 表示 turn 实际经历的 continuation 次数，而不是 attempt 数与 terminal 数的混合值
- `request_id`、`usage`、`ttft_ms`、`error`、`abort_reason`: 默认指向 turn-final terminal；若调用方需要逐 attempt 细节，应查看 `attempts[]`

明确禁止：

- 不能把某次 attempt 的 `tool_use` stop reason 写进 `TurnResult.stop_reason`
- 不能把 `attempts[-1]` 是否存在当成 turn-final 的替代判断
- 不能把 `completed` 和 child-run/session status 直接绑定

Why:

- 当前很多混乱正是来自 `run_turn()` 聚合层没有把 attempt 和 turn 语义拆开。
- 如果这里不写死，streaming surface 就算收紧了，non-streaming helpers 仍然会继续跑偏。

### 5E. 当前实现与目标 contract 的显式偏差清单

为了避免后续实现时再次回到“读代码猜设计”的状态，这里直接记录当前 runtime 与目标状态机 contract 的主要偏差。

| Area | Current implementation | Target contract | Impact |
| --- | --- | --- | --- |
| [engine.py](/Users/xyzjiao/AIProject/AIAgentRuntime/src/runtime/turn_engine/engine.py) event surface | `TERMINAL` 同时承担 attempt-final 与 turn-final 语义 | `TERMINAL` 只表示 turn-final，attempt 结束改走 `ATTEMPT_FINISHED` 或等价非终态载体 | host、tests、controller 都会误判 turn 已结束 |
| [engine.py](/Users/xyzjiao/AIProject/AIAgentRuntime/src/runtime/turn_engine/engine.py) tool continuation | assistant 输出 `tool_use` 时仍先发 `TERMINAL(stop_reason=\"tool_use\")` | `tool_use` 只能是 attempt outcome，不得冒充 final terminal | continuation path 与终态 path 混淆 |
| [engine.py](/Users/xyzjiao/AIProject/AIAgentRuntime/src/runtime/turn_engine/engine.py) max-turn exit | `while iteration < max_iterations` 落出后没有显式 final terminal | `max_turns` 必须产出唯一 final `TurnTerminalReason` | child-run / host 无法稳定观察到真实终态 |
| [engine.py](/Users/xyzjiao/AIProject/AIAgentRuntime/src/runtime/turn_engine/engine.py) failure precedence | provider/model error 仍可能在 stop phase 被改写成 `blocked` | failure-class terminal 需要保留原语义，不能降级成 waiting/blocking | session 可能错误进入 `WAITING` |
| [controller.py](/Users/xyzjiao/AIProject/AIAgentRuntime/src/runtime/session_runtime/controller.py) terminal consumption | 任意 `TERMINAL` 都会被当成当前 turn 的最终终态 | 只能消费 turn-final terminal；attempt outcome 不应驱动 session 投影 | session memory/persistence 会基于错误终态运行 |
| [agent_execution_service.py](/Users/xyzjiao/AIProject/AIAgentRuntime/src/runtime/agent_execution_service.py#L202) child-run projection | `completed=False` 一律推断成 `MAX_TURNS` | child-run status 必须基于显式 `TurnTerminalReason` 映射 | `error` / `blocked` / `interrupted` 被错误记成 `max_turns` |
| `TurnResult` 聚合 contract | `attempts[]` 与 `stop_reason` 都依赖旧 `TERMINAL` 事件面 | `attempts[]` attempt-scoped，`stop_reason` turn-final only | non-streaming helper 延续旧歧义 |

### 6. 增加统一的 budget / recovery policy surface

runtime 将新增 `BudgetAndRecoveryPolicy` 或等价控制面接口，在两个位置参与决策：

- assistant attempt 结束后
- tool replay 完成后

第一阶段它至少需要覆盖：

- `max_tokens` / 输出预算驱动的恢复
- tool-result budget / continuation budget
- reactive compaction
- max-turn exhaustion
- halt / retry / compact-and-retry / continue 的标准动作

第一阶段明确不要求：

- provider retry / fallback 策略统一收敛
- 为所有 provider-specific error reason 建立完整的恢复矩阵
- 把 controller、provider adapter、tool executor 里的所有局部恢复分支一次性并入单一策略表

Why:

- 参考实现风格主循环的价值之一就是把“恢复为什么发生”变成 runtime 决策，而不是 provider 细节。
- 当前 runtime 已有 compaction manager 和 tool executor metadata，但缺少连接它们的恢复控制面；第一阶段先把最关键的 budget/recovery join point 固定住，再逐步扩展 provider fallback。

Alternatives considered:

- 把恢复逻辑零散地放进 provider adapter、controller 或 tool executor。拒绝，因为这会破坏统一 continuation contract。

### 7. 保留专门子系统，不回退到 monolith

本 change 明确保留并继续复用：

- `StreamingToolOrchestrator`
- `select_tool_executor(...)`
- `CompactionManager`
- `RuntimeServices`

同时补齐：

- `PreCompact` / `PostCompact` phase dispatch
- transition reason observability
- sidecar invalidation / recovery wiring

Why:

- 当前 runtime 在工具执行控制面上已经比参考实现的单文件循环更模块化，这是应当保留的优点。
- 主循环 contract 要做的是“统一子系统接入方式”，不是“把所有子系统重新合并”。

Alternatives considered:

- 按参考实现的文件组织方式把更多逻辑重新塞回 `TurnEngine`。拒绝，因为这会把现有更好的模块设计退化掉。

## Risks / Trade-offs

- **[状态模型增多]** 新增 `TurnLoopState` / `Transition` / `PostEffects` 会增加抽象层。 → Mitigation: 先把模型做薄，只承载跨 phase 需要共享和观察的数据。
- **[sidecar 失效逻辑复杂]** 并发预取一旦遇到 compaction 或 recovery，容易出现旧结果污染。 → Mitigation: 由 supervisor 统一管理 generation id 和 restart 规则，不让各 service 自行决定。
- **[SessionController 与 TurnEngine 边界模糊]** stop 语义重构后，容易把 session 职责下沉过多。 → Mitigation: 规定 `TurnEngine` 只产出 `TurnPostEffects`，session commit 仍留在 controller。
- **[兼容性回归]** 改主循环容易伤到现有 streaming tool replay 和 golden tests。 → Mitigation: 保持 request/message/terminal 外部 contract 兼容，先在内部引入 phase 和 transition。
- **[预算策略过早复杂化]** 如果第一版把所有 recovery 规则一起做，会导致设计泛化。 → Mitigation: 第一阶段只强制统一 surface，优先接 `max_tokens`、tool-result budget 和 reactive compaction 三类恢复。

## Acceptance Invariants

以下不变量是本 change 的最终验收底线，任何实现只要违反其中一条，就说明状态机 contract 仍未真正收敛：

1. 每个 turn 恰好产出一个 final `TERMINAL`。
2. final `TERMINAL` 之后不能再有任何 turn event。
3. `tool_use`、`end_turn`、`error` 等 provider attempt 结束必须通过 attempt-level contract 表达，而不是复用 final `TERMINAL`。
4. 每个 turn 的所有退出路径都必须落到显式 `TurnTerminalReason`，包括 `max_turns`、`model_error`、`aborted_*`、`blocked`、`completed`。
5. `TurnResult.stop_reason` 只能表示 turn-final terminal reason。
6. `TurnResult.attempts[]` 只能表示 attempt-level outcome。
7. failure-class terminal reason 不能被 stop hook 或 waiting logic 改写成 `blocked` / `WAITING`。
8. session 和 child-run status projection 只能从 explicit terminal reason 得出，不能从 `completed: bool` 猜。

## Migration Order

这些偏差不能乱序修复，否则很容易出现半迁移状态。推荐实施顺序固定为：

1. 先改 [engine.py](/Users/xyzjiao/AIProject/AIAgentRuntime/src/runtime/turn_engine/engine.py) 的事件面：
   收回 host-facing `TERMINAL`，引入 `ATTEMPT_FINISHED` 或等价 attempt-level carrier。
2. 再改 [engine.py](/Users/xyzjiao/AIProject/AIAgentRuntime/src/runtime/turn_engine/engine.py) 的退出路径：
   保证 `max_turns`、`error`、`interrupted`、`blocked` 全部产出唯一 final terminal。
3. 再改 `TurnResult` 聚合：
   把 `attempts[]` 与 `stop_reason` 的层级语义拆开，清理 `completed` 的派生规则。
4. 再改 [controller.py](/Users/xyzjiao/AIProject/AIAgentRuntime/src/runtime/session_runtime/controller.py) 和 [agent_execution_service.py](/Users/xyzjiao/AIProject/AIAgentRuntime/src/runtime/agent_execution_service.py#L202) 的状态投影：
   统一切到 terminal-reason-driven classification。
5. 最后迁 host adapter、golden tests、background agent flow、非流式 helper 断言。

不建议反过来先改 projection 或 tests，因为旧 `TERMINAL` 语义还在时，这些修改只会制造更多过渡态歧义。

## Migration Plan

1. 新增 `TurnPhase`、`TurnLoopState`、`TurnTransitionReason`、`TurnRecoveryAction`、`TurnTerminalReason`、`TurnPostEffects` models，并把 attempt outcome 与 turn terminal 分离。
2. 在 `TurnEngine` 内部落地合法 phase 流转，禁止递归式 continuation，确保所有重入都经由 `advance_or_finish -> prepare`。
3. 收紧 event contract，保留 `TERMINAL` 给 turn-final，attempt 结束改走 `ATTEMPT_FINISHED` 或等价非终态事件/metadata。
4. 引入 pre-turn sidecar supervisor，先接 memory retrieval 和 hook context 两类 sidecar，并把 generation id / invalidation 语义做成统一 contract。
5. 接入 `PreCompact` / `PostCompact` phase，并把 compaction invalidation 规则纳入 sidecar supervisor。
6. 新增 budget / recovery policy surface，先让 `max_tokens`、tool-result budget、reactive compaction 走统一 recovery contract。
7. 让 `TurnEngine` 在所有退出路径上都产出唯一 `TurnTerminalReason`，`SessionController` 与 child-run projection 改为严格按照 terminal reason 分类。
8. 补齐 conformance tests，确保 streaming tool orchestration、ordered replay、blocked continuation、session waiting/interrupted projection、child-run status projection 和 resume 行为不回退。

Rollback strategy:

- 若 phase/state refactor 在中途证明过于扰动，可保留新 models 与 no-op policy/supervisor，实现上暂时回退到现有顺序逻辑；这样至少不会丢失统一 contract 和后续扩展点。

## Breaking / Compatibility Surface

- 第一阶段允许在内部同时保留旧 attempt terminal 数据结构和新 `ATTEMPT_FINISHED` payload，但 host-facing `TERMINAL` 必须立即收紧为 turn-final only。
- 现有消费方若依赖“`TERMINAL(stop_reason=tool_use)` 表示需要继续”的旧语义，必须迁移到 `ATTEMPT_FINISHED` 或等价 attempt metadata。
- `run_turn()` / `stream_until_idle()` / child-run store 的调用方必须统一迁移到“读 explicit turn terminal reason”的新 contract。
- golden tests、session host adapter、background agent status projection 必须作为同一批迁移对象处理，不能只改 engine 而保留旧断言。
- 若需要过渡期，可在 metadata 中临时保留旧字段镜像，但不得让旧字段重新成为主判断条件。

当前已知的主要 breaking surface 包括：

- 所有直接消费 `TurnStreamEventType.TERMINAL` 的 host/client
- [controller.py](/Users/xyzjiao/AIProject/AIAgentRuntime/src/runtime/session_runtime/controller.py) 的 turn terminal 消费逻辑
- `run_turn()` 的调用方对 `TurnResult.stop_reason` 和 `TurnResult.attempts[]` 的假设
- background child-run / run store / notification flow
- `test_query_turn_stream.py`、`test_query_runtime_protocol_golden.py`、`test_streaming_tool_runtime.py` 等锁定旧事件语义的测试

兼容迁移期间允许保留旧字段镜像，但不允许保留旧判断路径。

## Deferred Decisions

以下决策与本次 change 直接相关，但不应阻塞当前最小收敛范围，应明确列为后续演进项：

- `ATTEMPT_FINISHED` 最终是新增 `TurnStreamEventType`，还是以 metadata carrier 形式存在
- `AgentRunStatus` 是否新增 `INTERRUPTED` / `BLOCKED` 等更细粒度状态
- `SessionStatus.WAITING` 是否最终只对应 `blocking_limit` / `stop_hook_prevented`
- provider retry/fallback 是否与当前终态/恢复收敛一起做，还是后置
- sidecar supervisor、budget policy、recovery policy 的 deeper refactor 是否与事件语义迁移分两个阶段落地

## Open Questions

- memory retrieval sidecar 的 query snapshot 应以“最新 user prompt”为准，还是以“compaction 之后的完整 working context”作为失效判断主键？
- 第一版 budget/recovery 是否只覆盖 `max_tokens`、tool-result budget 和 reactive compaction，还是连 provider retry/fallback 一起收敛？
