## Context

当前 runtime 已经有可运行的 execution plane，但 interactive control plane 仍然散落在局部 callback 与 lifecycle stub 里。参考实现之所以能把 CLI、UI 与 SDK 收敛到一套运行时上，核心不在表层 while loop，而在一套真正参与 runtime flow 的 `HookBus`、permission system、elicitation pipeline 与 host bridge。

如果这几块继续分散在 tool runtime、session callback 与 host 外围包装中，后续 memory、compaction、skill policy 都只能建立在不稳定边界上。

## Goals / Non-Goals

**Goals:**

- 把 `HookBus`、`PermissionEngine`、`ElicitationService` 与 `HostRuntime`/`HostAdapter` bridge 收敛成同一 interactive control plane。
- 让 interactive 与 headless hosts 共享同一套 `SessionController`、`TurnEngine` 与 runtime routing 逻辑。
- 定义参考实现兼容 runtime hook phases、structured effects、permission modes、waiting/resume control flow 与 host-mediated interaction contract。
- 为 skill hooks、subagent permissions、future UI adapters 与 notification streaming 提供稳定边界。

**Non-Goals:**

- 不复刻参考实现的具体 terminal UI、Ink rendering 或 channel relay 产品逻辑。
- 不在本变更中实现 memory retrieval、compaction strategy 或复杂企业权限系统。
- 不改变用户编写 `ToolDefinition`、`AgentDefinition`、`SkillDefinition` 的基本定义格式。

## Decisions

### 1. 把 interactive runtime 看成单一 control plane，而不是三个分散子系统

本变更把 hooks、permission/elicitation 与 host bridge 视为一个阶段的一组协同能力，而不是三个彼此独立的 follow-up。

Why:

- 这三块共同定义参考实现风格 interactive runtime 的骨架。
- 若先做 hook 或 permission 而 host 仍停留在 lifecycle-only stub，runtime 仍无法形成统一交互控制流。
- 合并成单一阶段后，可以锁定完整的交互依赖方向：execution plane 只消费 control plane，host 只承接交互边界。

Alternatives considered:

- 继续拆成 `hook/permission` 与 `host bridge` 两个 changes。拒绝，因为这会把 interactive runtime 骨架拆断。

### 2. 使用 session-scoped `HookBus` 统一管理所有运行时钩子

runtime 将引入 session-scoped `HookBus`，负责 hook 注册、注销、matcher 解析、dispatch 与 structured effect 聚合。

Why:

- 参考实现的 hooks 是会影响 runtime flow 的 cross-cutting mechanism，而不只是 prompt augmentation。
- session-scoped ownership 更适合承接 skill 注册 hooks、host hooks 与 future compact hooks。
- 集中式 bus 能避免 `SessionController`、`ToolRuntime`、`SkillRuntime` 各自维护不同的 hook 调用链。

Alternatives considered:

- 继续把 hooks 当作 PromptComposer 的上下文来源。拒绝，因为它无法表达 `updated_input`、blocking、notification、elicitation short-circuit。

### 3. `PermissionEngine` 统一合并 tool policy、hook effects、session rules 与 host approval

权限决策由共享的 `PermissionEngine` 完成，统一合并：

- tool-level `check_permissions`
- hook-provided effects
- session permission context / mode / persistent rules
- host approval outcome

Why:

- 参考实现的 permission 不是工具私有逻辑，而是 runtime control plane。
- 只有集中化 engine 才能稳定支持 `default`、`dontAsk`、`bypassPermissions`、`bubble` 等模式。

Alternatives considered:

- 继续把 host prompt 直接挂在 tool runtime。拒绝，因为这会让 skill、subagent 与 tool 各自演化不同权限路径。

### 4. `ElicitationService` 是一般性交互入口，`ask_user` 只是其一个触发面

runtime 将引入 `ElicitationService` 作为结构化用户输入、`ask_user`、hook-satisfied responses 与 host-mediated follow-up 的统一入口。

Why:

- 参考实现的 elicitation 是 runtime 与 host 之间的通用交互能力，而不是单个 built-in tool。
- 分离 service 后，waiting/resume 可以在 session 层形成显式状态机。

Alternatives considered:

- 保留 `ask_user_handler` callback。拒绝，因为这会把通用交互能力绑死在一个 built-in tool 上。

### 5. `HostRuntime` 是 host adapter bridge，不拥有 orchestration

`HostRuntime`/`HostAdapter` bridge 负责：

- startup / ready / shutdown
- permission requests
- elicitation requests
- notifications
- turn event emission / consumption

但不负责：

- 主循环
- tool continuation
- transcript persistence
- subagent orchestration

Why:

- 参考实现的可复用 session/turn stack 位于 host 之下。
- 如果 host 拥有 orchestration，不同 host 会重新分叉 runtime 核心语义。

Alternatives considered:

- 让 host 自己接管 turn orchestration。拒绝，因为 CLI、SDK、UI 会再次出现多套 runtime。

### 6. skill、tool 与 subagent execution 共享同一 interactive control plane

skill invocation、tool execution 与 subagent execution 必须共享同一个 `HookBus`、`PermissionEngine`、`ElicitationService` 与 host bridge。

Why:

- 参考实现里 skill hooks、tool hooks、approval flow 与 `ask_user` 在运行时上是贯通的。
- 这为后续 `allowed-tools`、skill isolation、subagent policy inheritance 提供统一基础。

## Risks / Trade-offs

- **[交互控制流变复杂]** waiting、resume、interrupt 与 host responses 会让 session lifecycle 更复杂。 → Mitigation: 在 `SessionController` 中显式建模 waiting state，而不是隐式挂起 callback。
- **[合并顺序歧义]** tool policy、hook effects、session rules、host approval 的决策顺序容易产生歧义。 → Mitigation: 固定统一决策顺序，并用 golden tests 锁定。
- **[接口过宽]** 一次性引入 hook、permission、elicitation、host bridge 容易让 control plane 变重。 → Mitigation: 第一版只覆盖参考实现对齐所需核心交互点，不提前开放产品层扩展。

## Migration Plan

1. 引入 `HookBus`、`PermissionEngine`、`ElicitationService` 与 `HostRuntime` 协议及默认实现。
2. 将现有 `check_permissions`、`permission_handler`、`ask_user_handler` 与 host lifecycle callback 适配到新 control plane。
3. 让 `SessionController`、`TurnEngine`、`ToolRuntime`、`SkillRuntime` 与 subagent path 消费 shared interactive control plane。
4. 提供最小 CLI host 与 SDK host，验证共享 session/turn stack。
5. 增加 hook effects、permission modes、waiting/resume、host bridging 的回归测试。

Rollback strategy:

- 若 unified interactive control plane 引入严重行为回归，可暂时回退到 callback adapters，同时保留新的协议边界，避免再次回到无控制面的状态。

## Open Questions

- `PermissionRequest`、`Notification`、`ElicitationResult` 等扩展 phases 是否应在第一阶段一并进入 `HookBus`，还是先覆盖参考实现兼容核心 phases？
- reference CLI host 第一版应采用同步 stdin/stdout 还是 event-driven facade？
