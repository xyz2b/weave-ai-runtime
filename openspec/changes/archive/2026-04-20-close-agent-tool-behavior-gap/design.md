## Context

当前 runtime 在 agent/tool 方向最正确的地方，是主线程和 child agent 已经共享同一个 `TurnEngine`，而不是为 subagent 另起一套对话引擎。现有差距主要不在执行骨架，而在行为完整度：

- 模型主上下文里没有显式 `available_agents`，`main-router` prompt 也过薄，导致委派选择不稳定。
- 内置 `agent` tool 只有 `agent`、`prompt`、`background` 三个输入，child execution shaping 能力明显弱于参考实现。
- `AgentExecutionSpec` / `AgentRunRecord` 已经存在，但 child run 的消息历史、终态写入和 host 可见 lifecycle 还不够完整。
- `requested_model_route` / `requested_model` 已经在 execution contract 中出现，但还没有真正影响模型调用。
- `TurnEngine` 的 tool continuation 主路径仍然偏 streaming-only，complete-only provider 还不能走同一套 continuation contract。

这个 change 的目标不是重做 runtime 架构，而是在现有 control plane 上补齐这些行为缺口。

## Goals / Non-Goals

**Goals:**

- 让模型主上下文显式知道当前可委派的 agent 集合和各自职责。
- 让 `agent` tool 成为一个够用且可验证的 delegation contract，而不只是轻量 prompt passthrough。
- 为 sync、background、fork、denied 和 early-failed child runs 保留稳定的 sidechain observability。
- 让 `model_route` / `model` 真正参与 agent 执行选择，并进入 request/run metadata。
- 让 complete-only / buffered provider 也能走统一的 tool-call continuation 行为。
- 保持所有 agent execution 继续复用现有 `TurnEngine`、tool executor 和 orchestration 路径。

**Non-Goals:**

- 不引入新的 agent orchestration engine。
- 不实现完整 provider graph / marketplace / mailbox / swarm 平台能力。
- 不在本 change 中重写 skill system 或 memory system。
- 不要求现有 legacy `agent` tool 调用方式失效；旧格式应保持兼容。

## Decisions

### 1. 在 `TurnContext` 中显式暴露 `available_agents`，并把 router 指导写进 prompt

主线程 prompt 组装将从“只有 tools/skills 可见”扩展为“tools/skills/agents 都可见”。具体做法：

- 在 `TurnContext` 中新增 `available_agents` 字段。
- `TurnEngine` 在主线程组 prompt 时，从当前 agent registry 中取可见 agent，生成 `name + description` 列表。
- `ContextAssembler` 在 system prompt 中新增 `Agents:` 段落。
- 内置 `main-router` prompt 改写为显式决策顺序：直答、tool、skill、subagent。

这样做的原因是当前 runtime 已经有 `AgentCatalog` 和 agent registry，但这些信息停留在 tool capability context 里，没有进入模型主上下文；补这一步的收益最大，且不需要改动执行骨架。

备选方案：

- 只增强 `main-router` prompt，不新增 `available_agents`。拒绝，因为 prompt 仍然不知道当前 runtime 实际注册了哪些 agents。
- 让模型通过 tool capability context 自己探索 agent catalog。拒绝，因为主线程模型调用阶段并没有直接消费那套 capability container。

### 2. 扩展 `agent` tool，但仍以 `AgentInvocation` 为唯一 child execution 输入源

`agent` tool 将扩成正式 delegation contract，而不是再增加旁路接口。新增字段包括：

- `spawn_mode`
- `cwd`
- `model`
- `model_route`
- `reason`
- 可选的收窄型 `permission_mode`
- 可选的收窄型 `isolation`
- 可选的 `max_turns`

这些字段统一映射到 `AgentInvocation`，再由 `AgentDispatcher` 生成 `AgentExecutionSpec`。优先级固定为：

- 显式 `spawn_mode` 高于 legacy `background`
- tool 调用级 `cwd/model/model_route` 高于 agent 默认值
- child execution 只能收窄权限和隔离，不能突破 parent policy ceiling

返回 payload 也将补齐 child identity：

- `run_id`
- `parent_run_id`
- `turn_id`
- `status`
- `task_id`
- `requested_model`
- `requested_model_route`
- terminal summary 或 terminal metadata

这样做的原因是当前 system 已经有足够好的 execution contract，问题在于 tool surface 太薄，无法把执行差异显式传进去。

备选方案：

- 保持极简 `agent` tool，把更多控制面继续塞进 `metadata`。拒绝，因为这会继续制造隐式 contract。
- 为 `background`、`fork`、`route override` 再加多个专用 tools。拒绝，因为 delegation 入口会碎裂。

### 3. 把 child run 观测收敛到 sidechain store，而不是混入主 transcript

child agent 的运行记录将继续使用 `AgentRunRecord` 作为统一对象，但会补齐三类落点：

- `ChildRunStore`：存放 `run_id`、parent linkage、status、terminal metadata、messages
- host-visible lifecycle：主线程可观测 child started/running/completed/failed/denied
- runtime query surface：按 `run_id` 或 `session_id` 查询 child records

写入规则固定为：

- sync child 至少写 terminal record
- background child 至少写 `running` + terminal 两次
- denied / early-failed child 也必须写最小 record
- fork child 的 parent linkage 和 terminal hook 不能丢

主 transcript 仍只保留 continuation 所需消息，不复制 child 的完整内部消息。

这样做的原因是当前 execution contract 已经足够接近参考实现风格 sidechain，只差落地和查询面。继续把 child 历史塞进主 transcript 会污染主线程上下文，也不利于 background/fork 观测。

备选方案：

- 把 child messages 全量并回主 transcript。拒绝，因为会破坏 transcript 语义并导致主线程上下文膨胀。
- 只保留 task notification，不写 child run record。拒绝，因为 denied/failed/fork 路径会失去可追踪性。

### 4. 用最小 route binding 让 `model_route` 真正生效，不在本 change 中做完整 provider 平台化

为了只解决 agent/tool 行为差距，本 change 采用最小 route binding 方案：

- `AgentDefinition` 增加 `model_route`
- `RuntimeConfig` 增加命名 `model_routes`
- 每个 route 至少绑定：
  - `client`
  - `default_model`
  - `provider_name`
  - `capabilities`
- `AgentExecutionService` 负责解析最终 route
- `TurnEngine` 支持 request-scoped `model_client_override`

解析优先级固定为：

1. execution-time route override
2. agent-level `model_route`
3. inherited route hint
4. runtime default route

`model` 只允许覆盖已解析 route 的默认模型，不允许改变 provider ownership。

这样做的原因是用户当前只想补齐 agent/tool 行为，不想提前进入更大的 provider 平台化设计；最小 route binding 已足够让不同 agent 命中不同模型客户端。

备选方案：

- 继续保留单一 `model_client`，把 route 只作为 metadata。拒绝，因为 agent 的执行差异仍然是假的。
- 直接上完整 provider graph / binding assembly。当前不采用，因为会把 scope 扩大到平台化。

### 5. 在 `TurnEngine` 内部增加 buffered completion path，但复用现有 tool executor 语义

当前 `TurnEngine` 会直接走 `stream()`。本 change 将把 turn 执行分成两条内部路径：

- streaming path
- buffered completion path

buffered path 的原则是：

- 仍然产出同样的 assistant message
- 仍然从 assistant message 中抽出 tool calls
- 仍然复用当前 `BufferedToolExecutor` / `BatchToolExecutor` 的 finalize/orchestrator 语义
- terminal metadata 结构与 streaming path 对齐

这意味着差异只在“provider 响应何时可观察”，而不是上层 transcript、tool lifecycle、result continuation contract。

备选方案：

- 为 complete-only provider 另写独立 tool runtime。拒绝，因为会复制 orchestration 逻辑。
- 在 `complete()` 后把响应伪装成假的 streaming event 再重放。拒绝，因为实现上更绕，也更容易漂移。

## Implementation Appendix

### A. `agent` tool request/response contract is frozen in v1

为避免实现阶段继续猜测，本 change 将 `agent` tool 的 v1 contract 固定为：

`input_schema`

```json
{
  "type": "object",
  "properties": {
    "agent": {"type": "string"},
    "prompt": {"type": "string"},
    "background": {"type": "boolean"},
    "spawn_mode": {"type": "string", "enum": ["sync", "background"]},
    "cwd": {"type": "string"},
    "model": {"type": "string"},
    "model_route": {"type": "string"},
    "reason": {"type": "string"},
    "permission_mode": {
      "type": "string",
      "enum": [
        "default",
        "plan",
        "acceptEdits",
        "bypassPermissions",
        "dontAsk",
        "auto",
        "bubble"
      ]
    },
    "isolation": {"type": "string", "enum": ["none", "worktree", "remote"]},
    "max_turns": {"type": "integer", "minimum": 1}
  },
  "required": ["agent", "prompt"],
  "additionalProperties": false
}
```

约束固定为：

- `spawn_mode`
  - v1 只允许 `sync` 与 `background`
  - `fork` 保留为 skill-driven internal spawn mode，不作为 `agent` tool 的公开输入
- `background`
  - 作为 legacy 兼容字段保留
  - 若同时提供 `spawn_mode`，则忽略 `background` 并以 `spawn_mode` 为准
- `cwd`
  - 若为相对路径，则相对当前 tool context `cwd` 解析
  - 解析失败或越界时直接视为无效输入
- `model_route`
  - 映射到 `AgentInvocation.requested_model_route`
- `model`
  - 映射到 `AgentInvocation.requested_model`
- `reason`
  - 不参与 execution routing
  - 写入 `AgentInvocation.metadata["delegation_reason"]`
- `permission_mode`
  - 作为 child execution 的 requested override
  - 仅允许被 parent policy 和 agent definition 收窄，不允许扩权
- `isolation`
  - 作为 child execution 的 requested override
  - 仅允许被 parent policy 和 agent definition 收窄，不允许扩权
- `max_turns`
  - 作为 child execution 的 requested cap
  - 若 target agent 已声明 `max_turns`，则有效值取 `min(agent.max_turns, tool_input.max_turns)`

`output_schema`

```json
{
  "type": "object",
  "properties": {
    "agent": {"type": "string"},
    "status": {"type": "string"},
    "background": {"type": "boolean"},
    "run_id": {"type": "string"},
    "parent_run_id": {"type": ["string", "null"]},
    "turn_id": {"type": ["string", "null"]},
    "query_source": {"type": ["string", "null"]},
    "messages": {"type": "array"},
    "task_id": {"type": ["string", "null"]},
    "requested_model": {"type": ["string", "null"]},
    "requested_model_route": {"type": ["string", "null"]},
    "resolved_model_route": {"type": ["string", "null"]},
    "isolation_mode": {"type": ["string", "null"]},
    "terminal_metadata": {"type": "object"},
    "notification": {"type": ["object", "null"]}
  },
  "required": [
    "agent",
    "status",
    "background",
    "run_id",
    "parent_run_id",
    "turn_id",
    "query_source",
    "messages",
    "requested_model",
    "requested_model_route",
    "resolved_model_route",
    "terminal_metadata"
  ],
  "additionalProperties": false
}
```

返回约束固定为：

- 只要 child execution 已成功进入 dispatch，`run_id` 必须存在
- background child 首次返回时 `status=running`
- `terminal_metadata`
  - sync / denied / failed child 必须返回最终 terminal metadata
  - background child 初始返回可为空对象，终态以 child lifecycle event 和后续查询结果为准

### B. `available_agents` 的过滤规则固定为“当前可见且非当前 agent”

`available_agents` 的 v1 过滤规则固定为：

- 从当前 turn 可见的 agent registry entries 中取值
- 不按 `origin` 做额外过滤；bundled、user、project agents 都可见
- 排除当前 active agent 自己
- 保持 registry registration order，不额外排序

这意味着：

- root `main-router` turn 中，默认可见的 agent 集合不包含 `main-router` 自己
- child agent turn 中，如果未来也复用该字段，同样不包含当前 child agent 自己
- v1 不引入额外的 `delegatable` frontmatter，也不按 source 做白名单

`system prompt` 的 `Agents:` 段落也使用同一过滤后的集合，且每项只写：

- `name`
- `description`

不注入 agent 的完整 prompt、hooks 或 model route。

### C. child lifecycle host surface 固定为新的 `TurnStreamEventType.CHILD_RUN`

为避免 host surface 再次悬而未决，本 change 固定新增：

- `TurnStreamEventType.CHILD_RUN`
- `TurnStreamEvent.child_run: AgentRunRecord | None = None`

含义固定为：该事件直接携带“刚刚写入 sidechain store 的 child run record 快照”。

发射规则固定为：

- sync child
  - terminal record 写入后发射一次 `CHILD_RUN`
- background child
  - 初始 `running` record 写入后发射一次 `CHILD_RUN`
  - terminal record 更新后再次发射一次 `CHILD_RUN`
- denied / early-failed child
  - 最小 terminal record 写入后发射一次 `CHILD_RUN`
- fork child
  - 按其真实生命周期发射，与 sync child 保持一致

host 与 session contract 固定为：

- `SessionController` 像转发其他 turn events 一样转发 `CHILD_RUN`
- host adapter 不需要解析 transcript 或 notification 文本来推断 child 状态
- `child_run.status` 直接作为 host-visible truth source

本 change 不新增独立 `ChildRunLifecycleEvent` dataclass，也不把 child lifecycle 先降级成结构化 notification。

### D. `model_route` binding 和 buffered `complete()` normalization contract 固定为最小结构

`RuntimeConfig` 的最小 route binding 结构固定为：

```python
@dataclass(frozen=True, slots=True)
class ModelRouteBinding:
    name: str
    client: ModelClient
    default_model: str | None = None
    provider_name: str | None = None
    capabilities: NormalizedModelCapabilities | None = None
```

并新增：

- `RuntimeConfig.model_routes: tuple[ModelRouteBinding, ...] = ()`
- `RuntimeConfig.default_model_route: str | None = None`

`ModelRequest` 固定新增这些字段：

- `requested_model_route: str | None = None`
- `resolved_model_route: str | None = None`
- `provider_name: str | None = None`
- `resolved_capabilities: NormalizedModelCapabilities | None = None`
- `invocation_mode: str | None = None`

其中 `invocation_mode` 的 v1 取值固定为：

- `stream`
- `buffered_completion`

buffered `complete()` path 的 normalization contract 固定为：

- provider adapter 的 `complete()` 返回 `ModelResponse`
- `ModelResponse.message.content`
  - 必须已经是 runtime-native content blocks
  - 若包含 tool calls，必须使用结构化 `ToolUseBlock`
- 本 change 不实现“从纯文本里解析 tool call”的 fallback

terminal metadata 归一规则固定为：

- 若 `ModelResponse.terminal` 非空，则直接使用
- 否则 runtime 从这些字段构造 `ModelTerminalMetadata`
  - `stop_reason`
  - `usage`
  - `request_id`
  - `ttft_ms`
- `abort_reason` 和 `error` 仅在明确存在时填充

buffered continuation 规则固定为：

- 先提交 assistant message
- 再从 `ToolUseBlock` 抽出 tool calls
- 再走现有 tool executor / orchestrator finalize 路径
- tool result replay 顺序仍按原始 `tool_use` 顺序，而不是完成顺序

## Risks / Trade-offs

- [Prompt 变长] → `available_agents` 只暴露 `name + description`，不注入完整 prompt。
- [扩展后的 `agent` tool 更容易被模型误用] → 在 validate 阶段做冲突检查，并定义稳定 precedence，避免运行时猜测。
- [child run store 增加重复数据] → sidechain 只承载 child 内部历史，主 transcript 不做镜像。
- [route-aware execution 增加测试矩阵] → 通过 fake clients 覆盖 route precedence、same-session multi-route、terminal metadata propagation。
- [buffered path 与 streaming path 漂移] → 抽共享 normalization helper，确保 assistant message、terminal metadata、tool result continuation 复用同一组组装规则。

## Migration Plan

- `agent` tool 保持旧输入兼容；缺省时仍接受 `agent`、`prompt`、`background`。
- 若未配置 `model_routes`，runtime 继续回退到现有全局 `model_client` 路径。
- `background` 旧布尔字段内部会映射到 `spawn_mode`，但新逻辑以显式 `spawn_mode` 为准。
- child run store 默认仍可回退为内存实现；新增持久化 store 时不影响现有 session transcript contract。
