## Context

当前 runtime 已经支持：

- 从 `SKILL.md` 解析 `allowed-tools`、`hooks`、`context`、`agent`
- 从 agent 定义解析 `permissionMode`、`memory`、`isolation`
- 以 inline 或 forked 方式执行 skill

但这些能力大多还停留在“字段被解析出来了”这一层。真正缺少的是 Claude Code 风格的 runtime policy semantics：

- skill 是否只能收窄 capability，而不能扩大 capability
- inline skill 与 forked skill 分别如何继承 permission、hooks 与 tool pool
- skill 注册 hooks 的 ownership 与清理语义
- `none`、`worktree`、`remote` 如何成为真正的执行隔离 contract

这一步不补齐，`Tool`、`Agent`、`Skill` 三套用户接口虽然能定义，但还不能形成稳定闭环。

## Goals / Non-Goals

**Goals:**

- 定义 skill policy semantics，使 inline、forked、delegated execution 的 capability 与 policy 继承关系可验证。
- 将 skill policy 与 interactive control plane 贯通，使 skill invocation 进入统一的 permission、hook 与 elicitation 决策流。
- 把 `none`、`worktree`、`remote` 升级为 runtime isolation contract，而不是仅有枚举值。
- 明确 skill-owned hooks、tool pool narrowing、subagent inheritance 与 non-escalation semantics。

**Non-Goals:**

- 不在本变更中实现完整的 remote execution product surface。
- 不重新设计 `ToolDefinition`、`AgentDefinition`、`SkillDefinition` 的对外格式。
- 不把 isolation 设计成任意容器或 sandbox 编排平台。

## Decisions

### 1. skill policy 只允许收窄 capability，不允许隐式升级

skill invocation 的 policy 解析遵循 non-escalation 原则：

- parent agent / session 暴露的 capability 是上界
- skill `allowed-tools` 只能进一步收窄
- forked skill / delegated agent 不能绕过 parent permission context

Why:

- Claude Code 的 skill 更像对 runtime 能力的受限包装，而不是 capability escalation surface。
- 只有 non-escalation 规则稳定，用户才容易推理 skill 的安全边界。

Alternatives considered:

- 允许 skill 通过 frontmatter 扩大工具池。拒绝，因为这会让 skill 变成隐式提权入口。

### 2. inline 与 forked skill 共享一套 policy envelope，但执行边界不同

inline 与 forked skill 都会先解析同一个 policy envelope，再根据执行模式决定：

- inline：在当前 turn/session 上下文中执行，但受 narrowing 后的 capability 与 hook ownership 约束
- forked：在 delegated agent context 中执行，但继承 parent session 的 policy 上界与 permission context

Why:

- 这能避免 inline 和 forked skill 演化出两套互不兼容的 policy 语义。

### 3. skill 注册的 hooks 必须具备 ownership 与生命周期清理

skill 注册的 hooks 将被标记为 invocation-owned registration，并在 skill 生命周期结束后清理。

Why:

- 没有 ownership，skill hooks 很容易泄漏到后续 turn 或其他 invocation。
- 这也是 Claude 风格 runtime policy 的关键部分。

### 4. isolation 通过 `IsolationManager`/adapters 执行，而不是只修改 cwd

runtime 将把 `none`、`worktree`、`remote` 收敛为统一 isolation contract，由 isolation manager 或 adapters 负责：

- 准备执行环境
- 暴露受控 cwd / workspace handle
- 记录 isolation metadata
- 在需要时清理生命周期资源

Why:

- 当前只改 `cwd` 的做法不足以成为真正的 isolation contract。
- 统一 contract 才能让 worktree 与 remote 在同一 runtime 语义下演进。

Alternatives considered:

- 继续把 isolation 视作 agent runtime 的局部 helper。拒绝，因为这无法承接后续 remote/worktree 的真实语义。

### 5. subagent execution 必须显式继承 policy、memory 与 isolation 上下界

delegated execution 不只是 tool pool 裁剪，还必须显式继承：

- permission context 上界
- skill availability 上界
- memory scope 上界
- isolation contract 或更窄限制

Why:

- Claude 风格的 subagent 并不是“重新启动一个无约束 agent”。
- 这样 `main-router`、skill fork 与 background agent 才会形成统一 delegation semantics。

## Risks / Trade-offs

- **[策略规则变复杂]** skill、agent、session 多层 policy 合并容易产生歧义。 → Mitigation: 固定 non-escalation 顺序，并为 inline/forked/delegated 三条路径做 fixtures。
- **[isolation 先有 contract、后有强实现]** 第一版可能先稳定接口，再逐步补强 worktree/remote。 → Mitigation: 明确 contract 与 default behavior，并通过适配器隔离后续实现差异。
- **[hook ownership 清理不当]** skill hooks 泄漏会污染会话。 → Mitigation: 把 registration ownership 纳入 hook bus 模型，并增加生命周期测试。

## Migration Plan

1. 新增 skill policy envelope、policy resolver 与 isolation contract。
2. 将 inline skill、forked skill 与 delegated agent path 统一接入 policy narrowing 与 permission inheritance。
3. 将 skill-owned hook registration 与 cleanup 接入 shared hook bus。
4. 将 `none`、`worktree`、`remote` 迁移到统一 isolation manager/adapters。
5. 增加 capability narrowing、hook ownership、isolation lifecycle 与 delegated execution 的测试。

Rollback strategy:

- 若完整 isolation enforcement 暂时过重，可保留统一 contract 与 no-op/default adapters，同时避免再次退回到仅靠枚举占位的状态。

## Open Questions

- `remote` isolation 第一阶段是否只需要 contract + stub adapter，还是需要最小可运行 transport？
- skill policy 是否需要显式诊断面，向 host 暴露“为什么某个 tool/skill 被收窄或拒绝”？
