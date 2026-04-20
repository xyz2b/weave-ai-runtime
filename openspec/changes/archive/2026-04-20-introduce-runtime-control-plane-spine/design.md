## Context

当前 runtime 已经形成了 `RuntimeKernel -> SessionController -> TurnEngine -> Tool/Agent/Skill runtimes` 的基础执行链路，但 control plane 相关能力仍然以零散 callback、placeholder 类型和局部 wiring 的方式存在。这样虽然足够支撑最小 headless demo，却无法稳定承接参考实现的 hooks、permissions、elicitation、memory、compaction 与 host bridge 等 cross-cutting 能力。

现有问题主要集中在三点：

- runtime assembly 还没有显式的 control-plane service graph
- execution plane 仍然通过 callback 注入消费控制逻辑，缺乏稳定的依赖边界
- prompt/context 装配还只是字符串拼接器，不是 control-plane aware 的上下文装配器

## Goals / Non-Goals

**Goals:**

- 引入统一的 runtime control-plane spine，使 kernel 能显式装配共享服务对象。
- 定义 control plane 与 execution plane 的稳定依赖方向，避免继续通过 callback 扩散运行时职责。
- 为 hooks、permissions、elicitation、memory、compaction 与 host runtime 预留清晰接口，而不是把这些逻辑继续塞进 TurnEngine。
- 保持 SessionController 与 TurnEngine 的 host-independent 特性。

**Non-Goals:**

- 此变更不直接实现 hooks、permissions、elicitation、memory、compaction 的完整行为。
- 不在本变更中引入具体 CLI/TUI/UI 交互逻辑。
- 不重写现有 turn/message protocol，也不改变现有 built-in tools/agents/skills 的表面契约。

## Decisions

### 1. 引入统一的 `RuntimeServices` 聚合控制面依赖

runtime 将新增一个显式的 `RuntimeServices` 聚合对象，用于承载 hook bus、permission engine、elicitation service、memory manager、compaction manager、host runtime、task manager 与 transcript store 等控制面能力。

Why:

- 现有 callback 式 wiring 无法表达控制面依赖图，也不利于后续增量扩展。
- 参考实现的主循环不是只靠几个局部 callback 维持，而是依赖一套共享 control plane。
- 聚合对象比把每个 service 独立穿透到所有构造函数更容易管理依赖与测试边界。

Alternatives considered:

- 继续沿用 `configure_runtime(...)` 式 callback 注入。拒绝，因为这会继续放大 ad hoc wiring。
- 为每个子系统分别手工注入所有 control-plane service。拒绝，因为这会让构造签名迅速膨胀。

### 2. 明确分离 control plane 与 execution plane

runtime 将显式区分：

- control plane：session control、hooks、permissions、elicitation、memory、compaction、host bridge、transcript、tasks
- execution plane：turn engine、tool runtime、agent runtime、skill runtime

Why:

- 参考实现的稳定性来自这些 cross-cutting systems 的协调，而不是单纯的 tool loop。
- 这种分层能避免把 permissions、hooks、memory 等长期塞进 TurnEngine。
- execution plane 更适合被 headless 与 interactive hosts 复用。

Alternatives considered:

- 继续让 TurnEngine 同时承担主要控制逻辑。拒绝，因为这会让它变成新的 `QueryEngine` 巨型类。

### 3. kernel 负责装配，session/turn 负责消费

`RuntimeKernel` 负责构建 service graph，`SessionController` 和 `TurnEngine` 只消费已装配好的服务，不再自行拼装 runtime dependencies。

Why:

- bootstrap 生命周期和 turn 生命周期不同，装配应留在 kernel。
- 这样有利于在 host bindings、provider bindings、test doubles 之间替换底层实现。

Alternatives considered:

- 让 `SessionController` 或 `TurnEngine` 在运行时懒初始化控制面对象。拒绝，因为这会让生命周期边界变得模糊。

### 4. 把 prompt composition 提升为 control-plane aware 的上下文装配

现有 `PromptComposer` 将保留其用途，但会朝“上下文装配器”演进，使 memory fragments、hook context、compaction outputs 与 runtime metadata 都通过统一装配边界进入 request context。

Why:

- 参考实现的 system prompt 与 context 不是简单字符串拼接，而是多来源控制面信息的稳定装配结果。
- 未来 memory 与 compaction 接入后，需要一个稳定位置承接这些贡献。

Alternatives considered:

- 将 memory、hook、compaction 各自直接拼进 TurnEngine。拒绝，因为那会复制装配逻辑并打散控制面边界。

## Risks / Trade-offs

- **[抽象先行]** 先引入 control-plane spine 可能会增加短期样板代码。 → Mitigation: 先用 no-op/default services 落地骨架，再逐步填充具体能力。
- **[迁移成本]** 现有测试依赖 callback wiring，改造后需要更新装配方式。 → Mitigation: 在迁移期提供兼容 adapter，把旧 callback 包进新 service graph。
- **[边界过粗]** `RuntimeServices` 可能演化为过大的“上帝对象”。 → Mitigation: 保持聚合对象只做 service wiring，不承载业务逻辑。

## Migration Plan

1. 新增 `RuntimeServices` 与 control-plane service 协议。
2. 将 `RuntimeKernel` 改为先装配 service graph，再装配 session/turn execution stack。
3. 让 `TurnEngine`、`ToolRuntime`、`AgentRuntime`、`SkillRuntime` 通过 `RuntimeServices` 消费控制面能力。
4. 用 no-op 或 adapter 实现保持现有测试与 runtime 行为可运行。
5. 再在后续变更中逐步填充 hooks、permissions、host、memory、compaction 的真实实现。

Rollback strategy:

- 如该 spine 设计证明不成立，可回滚到 callback wiring；由于本变更主要是内部装配重构，不要求立即改变用户定义格式，因此回滚风险可控。

## Open Questions

- `RuntimeServices` 是否需要细分为只读 `RuntimeView` 与可变 `RuntimeServices` 两类对象，以进一步约束依赖方向？
- `PromptComposer` 是否应直接重命名为 `ContextAssembler`，还是先保持兼容命名、逐步演进？
