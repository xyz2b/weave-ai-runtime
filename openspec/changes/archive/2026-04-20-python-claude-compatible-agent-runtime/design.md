## Context

当前仓库已经在 `cc-src` 和 `docs/cc` 中沉淀了大量 Claude Code 架构的源码解读，但还没有把这些内容正式收敛成一个可复用 runtime framework 的设计方案。目标方向现在已经明确：

- 实现语言选择 Python
- 面向用户的 `Tool`、`Agent` 和 `Skill` 定义保持与 Claude Code 兼容
- memory 第一版沿用 Claude Code 的默认实现思路
- hooks 既要覆盖 Claude Code 兼容的 runtime phase，也要覆盖 host 集成需求
- 框架必须提供一个内置主线程 routing agent，以及一组精简但实用的内置 tools 和 skills

Claude Code 源码显示，稳定的核心并不是 Ink UI，而是 bootstrap、session control、query loop、tool orchestration、memory 与 hooks 的组合。Python runtime 应当把这些层显式化，而不是像 Claude Code 一样把大量职责隐含在 REPL 实现里。

## Goals / Non-Goals

**Goals:**

- 设计一个 Python runtime 架构，保持 Claude Code 兼容的 tools、agents、skills、memory 与 hooks 语义。
- 通过显式的 `SessionController` 收敛 session control，而不是让这部分职责散落在 UI 与 loop 代码中。
- 通过内置 `main-router` agent 显式建模主线程 routing 角色。
- 保持 runtime 与 host 无关，使 CLI、TUI、SDK、channel 等宿主可以接入同一套 turn engine。
- 提供一组默认内置的 agents、tools 与 skills，使 runtime 在没有用户自定义定义时也能直接工作。

**Non-Goals:**

- 不按行把 Claude Code 从 TypeScript/Bun 迁移到 Python。
- 不保留 React/Ink 的渲染契约或终端组件内部实现。
- 第一版不支持用户自定义 memory backend；先只保留 Claude Code 风格的文件型 memory。
- 不复刻 Claude Code 内部所有 Anthropic 专用或产品专用 feature gate。
- 第一阶段不承诺完整覆盖 plugin 与 MCP 的发现能力，只实现支撑 runtime 设计所需的兼容面。

## Decisions

### 1. 采用“语义兼容”，而不是“源码兼容”

Python runtime 将保留 Claude Code 面向用户的定义字段、加载规则和行为语义，但不会去模拟 TypeScript 类型系统或 Bun 特有基础设施。

Why:

- 这样能让已经基于 Claude Code 心智模型工作的用户以更低成本迁移
- 可以避免 Python runtime 被 React、Bun 或 Anthropic 产品细节绑定
- 兼容目标聚焦在真正由用户编写的“定义层”

Alternatives considered:

- 重新设计一套 Python 原生定义模型。拒绝，因为这会直接丢掉 Claude Code 兼容性和用户已有认知。
- 直接翻译 TypeScript 类型。拒绝，因为那是在复刻语法，而不是复刻行为契约。

### 2. 将 runtime 拆成 kernel、session、turn-engine 与 host 四层

runtime 将分成四个层次：

- `RuntimeKernel`：bootstrap、registries、配置、built-in 加载、持久化装配
- `SessionRuntime`：`SessionController`、队列、interrupt/resume、状态管理
- `TurnEngine`：prompt composition、model loop、tool orchestration、stop handling
- `HostAdapters`：CLI、TUI、SDK、channel 或未来其他宿主接入层

Why:

- Claude Code 源码表明真正可复用的核心位于 REPL 之下
- host adapters 需要 hooks、permissions 和渲染，但不应拥有 turn engine
- 这种拆分能让同一个 runtime 同时服务 headless 和 interactive 场景

Alternatives considered:

- 保持单一的 REPL-centric runtime。拒绝，因为这会让非 CLI 宿主始终是二等公民。
- 把所有内容收进一个 `QueryEngine` 类。拒绝，因为 startup、session control 与 turn execution 的生命周期和扩展点明显不同。

### 3. 把主线程显式建模为内置 `main-router` agent

runtime 将内置一个 `main-router` agent，作为默认主线程对话 agent。它负责：

- 直接回答
- 直接调用工具
- 调用 skill
- 委派 subagent
- 结束当前 turn

Why:

- Claude Code 里这个角色已经隐式存在于主循环中，但不是一等 agent
- 把它显式化后，可以形成稳定的扩展点和测试边界
- 这样主线程行为与 subagent 行为会落在同一套 agent 模型之下

Alternatives considered:

- 把 routing 保留在 session controller 的控制逻辑里。拒绝，因为这会把核心行为隐藏在控制流里，而不是暴露为真实 runtime 实体。
- 单独增加一个 intent classifier agent。拒绝，因为主线程角色远不止“意图识别”。

### 4. 保持 tool、agent 与 skill 通过 registry 驱动加载

Python runtime 将使用独立的 tools、agents 与 skills registries。来自 bundled、user 与 project 的定义会先被标准化，再由 registry 在 session startup 和 turn execution 阶段统一解析。

Why:

- Claude Code 已经把定义加载和执行行为分离开了
- registry 驱动有利于 built-ins 与用户覆盖规则保持稳定可预测
- 这也能简化 host 集成，因为 host 消费的是解析后的 registry，而不是零散文件

Alternatives considered:

- 每个 session 直接从文件系统加载定义。拒绝，因为这会让 session startup 与文件发现强耦合，也让 override 语义更难推理。

### 5. 将 Claude Code 的 memory 语义保留为默认 provider

第一版将实现一个默认文件型 memory provider，参考 Claude Code 的流程：

- memory 目录解析
- `MEMORY.md` prompt 注入
- turn 之前的 relevant-memory 检索
- 主线程 turn 结束后的 memory 提取
- agent memory scope

Why:

- 用户已经明确要求 memory 先按 Claude Code 的方式实现
- memory 是明显的跨层能力，应该先把默认行为稳定下来，再开放自定义
- 即便后面要抽象 provider 边界，也不应该丢掉默认兼容行为

Alternatives considered:

- 完全延后 memory。拒绝，因为 memory 是目标框架中的核心部分之一。
- 一开始就把 memory 做成完全可插拔。拒绝，因为这会在默认行为尚未稳定前扩大范围。

### 6. 把 hooks 视为事件总线，而不是简单 shell 回调

runtime 将支持 Claude 兼容的 runtime hook phases，例如 `SessionStart`、`UserPromptSubmit`、`PreToolUse`、`PostToolUse`、`Stop`、`SubagentStop`、`SessionEnd`。同时也会增加 host lifecycle hooks，用于把 CLI 或 UI 的启动、关闭等逻辑纳入 runtime 主流程，而不是把这些逻辑硬编码到 turn engine 里。

Why:

- Claude Code 的 hooks 是明显的 cross-cutting mechanism，参与验证、prompt augment、permission flow 与 cleanup
- host startup 逻辑属于 runtime integration，而不属于 conversation loop 本身
- 用统一事件总线建模 runtime 和 host 扩展，整体会更一致

Alternatives considered:

- 只保留 Claude 兼容的 runtime hooks。拒绝，因为用户明确要求为 host 逻辑预埋 hook。
- 把 CLI/TUI startup 直接硬编码进 bootstrap。拒绝，因为这会削弱嵌入能力和复用性。

### 7. 提供一组精简的内置 runtime pack

runtime 将默认随附一组 built-in，而不是空白 runtime。

Built-in agents:

- `main-router`
- `general-purpose`
- `explore`
- `plan`
- `verification`

Built-in tools:

- `read`
- `edit`
- `write`
- `glob`
- `grep`
- `bash`
- `web_fetch`
- `web_search`
- `agent`
- `skill`
- `task_create`
- `task_get`
- `task_update`
- `task_list`
- `task_stop`
- `ask_user`
- `sleep`

Built-in skills:

- `verify`
- `debug`
- `stuck`
- `batch`
- `simplify`
- `remember`

Why:

- runtime 需要一个可直接使用的 baseline，不能完全依赖用户自定义
- 这些 built-ins 足以支撑 routing、探索、规划、验证和 memory 维护
- 它们反映的是 Claude Code 中通用且 runtime 级的能力，而不是产品专用辅助功能

Alternatives considered:

- 不提供任何 built-ins。拒绝，因为这样很难验证 runtime 的端到端可用性。
- 把 Claude Code 的所有 built-ins 都搬过来。拒绝，因为其中很多能力是产品特定的，而不是 runtime 必需的。

## Risks / Trade-offs

- **[兼容性漂移]** Python 行为可能在大体语义上兼容 Claude Code，但在边界情况下仍有偏差。 → Mitigation: 尽早增加定义级 fixtures 和兼容性测试。
- **[架构范围过大]** 一次变更同时覆盖 kernel、session control、tools、agents、skills、memory、hooks 与 built-ins，容易导致实现范围膨胀。 → Mitigation: 通过分层任务顺序强制先做核心能力。
- **[memory 复杂度]** memory retrieval 与 extraction 都是跨层行为，容易与 session logic 缠在一起。 → Mitigation: 即便只实现默认 provider，也要先把 memory 独立成子系统边界。
- **[host 耦合]** startup 与 shutdown hooks 如果处理不当，会把 host 关注点反渗入 runtime core。 → Mitigation: 区分 Claude-compatible runtime events 与 host lifecycle hooks，但仍通过同一 hook bus 暴露。
- **[内置面持续扩张]** built-ins 一旦成为框架表面的一部分，就会变成兼容性承诺。 → Mitigation: 第一版只保留精简且 runtime-focused 的 built-in pack。

## Migration Plan

1. 先落地 Python runtime 提取的 proposal、design、specs 与 tasks。
2. 首先创建 Python 包结构以及 registry interfaces。
3. 先实现 session control 与 turn execution，再接入 host integrations。
4. 等 turn engine 稳定后，再补默认 memory 子系统与 hook 系统。
5. 在 core protocols 与 registries 可运行后，再补 built-in runtime pack。
6. 在扩大 host 或 extension 支持之前，先通过 fixture-driven tests 验证兼容面。

Rollback strategy:

- 如果 runtime 提取最终证明方案不可行，可以回滚实现层工作，而不会影响现有 Claude Code 解读材料，因为这次变更新增的是一个独立的 Python runtime 面，而不是修改 `cc-src` 本身。

## Open Questions

- plugin 与 MCP 型定义源是否应进入第一阶段 Python 实现，还是等 bundled、user、project 三类来源稳定后再补？
- built-in skills 应该保持 markdown-first，还是允许 Python callable 与 markdown 混合存在？
- turn engine 下层的 model client abstraction 应该如何设计，才能让 Claude 兼容行为跨 provider 保持稳定？
