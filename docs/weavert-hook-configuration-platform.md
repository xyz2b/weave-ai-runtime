# Runtime Hook 配置平台

runtime 现在在 session-scoped `HookBus` 之上提供了一套公开的 Hook 配置平台，用来向 runtime 接入方暴露稳定的注册入口、生命周期阶段和诊断能力。

本文只回答两个问题：

1. 这套 Hook 平台的对象模型是什么。
2. 按这份文档，怎样写出一个最小可运行的 Hook。

如果你只想先跑通一个最小示例，先看 `demos/README.md` 里的 `session.register_hook(...)` demo。  
本文保留为 Hook registration model、phase contract 和诊断语义的说明文档；推荐 surface 是 runtime config / host / session / turn API，以及 skill hooks。agent-owned hooks 不是这里要鼓励的默认 authoring path。

## 1. 这套 Hook 平台的对象模型

### 1.1 适用场景

这套平台适合下面几类扩展需求：

- 在 `PreToolUse` / `PostToolUse` 阶段插入审批、拦截、审计或工具输入输出整形逻辑。
- 在 `PostContextAssemble` / `PreModelRequest` 阶段做上下文裁剪、模型路由、请求参数覆盖。
- 在 `PostModelResponse` / `Stop` / `RecoveryDecision` 阶段做恢复控制、人工确认、失败后重试。
- 在 `Notification` / `Elicitation` / `ElicitationResult` 阶段接入宿主交互、人工输入或外部协同。
- 在 `SessionStart` / `SessionEnd` / `SubagentStop` 等阶段观察运行时生命周期并产出诊断或审计记录。

如果你的需求是“在不改 runtime 主循环的前提下，把业务控制逻辑注入到某个稳定生命周期节点”，那就应该看这份文档。

### 1.2 平台的核心是什么

这套平台建立在 session-scoped `HookBus` 之上。可以把它理解成 runtime 主循环里的统一 Hook 调度中心：

- runtime 负责定义哪些 phase 是稳定的公开注入点。
- 各类来源的 Hook 定义最终都会被归一化到同一套注册模型。
- Hook 的匹配、执行、合并、阻断、覆盖和诊断，最终都通过同一个 `HookBus` 完成。

也就是说，这个平台的重点不是“某个单独的回调函数”，而是“一套可注册、可观察、可诊断的 Hook 生命周期模型”。

### 1.3 Hook phase 是公开的注入点

公开 phase 现在分成两层：

- stable public
  - `SessionStart`
  - `SessionEnd`
  - `PreToolUse`
  - `PostToolUse`
  - `PostToolUseFailure`
  - `PreModelRequest`
  - `PostModelResponse`
  - `Stop`
  - `Notification`
  - `Elicitation`
  - `ElicitationResult`
- advanced public
  - `UserPromptSubmit`
  - `SubagentStop`
  - `PreCompact`
  - `PostCompact`
  - `PreContextAssemble`
  - `PostContextAssemble`
  - `RecoveryDecision`

任何未列出的 phase 都会被视为 `internal-only`，并被公开注册 API 拒绝。

工程上可以这样理解：

- stable public：ordinary v1 hook contract，普通接入方默认应只依赖这里
- advanced public：仍可用，但不属于 ordinary v1 portability promise
- internal-only：实现细节，不应被公开注册面依赖

### 1.4 一个 Hook 注册项由哪些对象组成

一个公开 Hook 注册项，核心是 `HookRegistrationRequest`。它通常由下面几部分组成：

- `phase`
  表示这个 Hook 挂在哪个公开生命周期阶段。
- `match`
  表示命中条件，常见写法是按 `target` 匹配某个工具或对象。
- `scope`
  表示 Hook 的生命周期边界。
- `handler`
  表示 Hook 被触发后实际执行什么逻辑。
- `contract`
  表示这个 Hook 允许输出哪些 effect 字段。
- `once` / `metadata`
  分别表示是否只生效一次，以及附加元数据。

其中最重要的几个对象如下。

`HookRegistrationScope`

- `session-template`
  适合 runtime / host 级模板注册，后续会物化到具体 session。
- `session`
  适合整个 session 生命周期内持续生效的 Hook。
- `turn`
  仍然可用，但属于 advanced registration surface。

`HookHandlerManifest`

- stable public handler
  - `callback`
    - 进程内回调
    - 是唯一被 ordinary-v1 保证的 handler kind
- advanced / package-specific handlers
  - `http`
  - `command`
  - `agent`
  - `prompt`

`HookEffectContract`

- 用来声明哪些 effect 字段是稳定可消费的。
- 如果 Hook 返回了当前 phase 不支持的 effect 字段，这些字段会被忽略，并在诊断信息里体现。

下面先看 helper path。它仍然会生成普通 `HookRegistrationRequest`，只是把常见 callback、matcher 和 scope 组装步骤收起来：

```python
from weavert.hooks import (
    HookDispatchTraceQuery,
    HookInventoryQuery,
    block_execution,
    match_tool,
    on_pre_tool_use,
)

handle = session.register_hook(
    on_pre_tool_use(
        lambda _payload: block_execution(),
        match=match_tool("deploy"),
        scope="turn",
        effects=(block_execution,),
    )
)

inventory = session.list_hooks(HookInventoryQuery(phase="PreToolUse"))
traces = session.list_hook_dispatch_traces(HookDispatchTraceQuery(phase="PreToolUse", limit=20))
```

如果你传的是 `scope="turn"`，这个片段同样假定当前 session 已经处于活跃 turn 中。

什么时候优先用 helper path：

- 你只是在 stable public phase 上写普通 callback Hook。
- 你只需要常见 matcher，例如某个 tool name 或简单 pattern。
- 你希望 `rewrite_input(...)`、`block_execution(...)`、`notify(...)`、`respond_to_elicitation(...)` 这类常见 effect 自动带上对应的 contract 意图。

什么时候继续直接写 raw `HookRegistrationRequest`：

- 你要显式控制低层 `HookEffectContract`、`HookHandlerManifest` 或非 helper 覆盖到的 effect 字段。
- 你要用 advanced phase、外部 handler kind、definition document authoring，或其他不属于普通 callback 的路径。
- 你已经需要把 scope、policy、contract、diagnostics 都完整展开，helper 不再明显减小样板代码。

注册完成后，你会拿到一个 `handle`：

- `handle.activation_state` 会暴露 `pending_activation`、`active`、`released`、`expired` 或 `rejected`。
- `handle.release()` 是幂等的。

### 1.5 Hook 可以从哪些层注册

这套平台不是只有一种注册入口。它支持多层注册面，最终都会收敛到同一模型。

`runtime config`

- 适合声明“所有 session 启动时都应该具备”的模板化 Hook。
- 推荐使用规范的 `hooks.handlers` + `hooks.registrations` 结构。

```python
from weavert.runtime_kernel import RuntimeConfig, assemble_runtime

weavert = assemble_runtime(
    RuntimeConfig(
        hooks={
            "handlers": {
                "runtime_context_override": {
                    "kind": "callback",
                    "binding": "runtime_context_override",
                }
            },
            "registrations": [
                {
                    "phase": "PostContextAssemble",
                    "handler": {"ref": "runtime_context_override"},
                    "contract": {"effect_fields": ["request_override", "metadata"]},
                }
            ],
        }
    )
)

weavert.bind_hook_callback(
    "runtime_context_override",
    lambda _payload: {"request_override": {"requested_model_route": "runtime-route"}},
)
```

`host API`

- 适合宿主层统一挂载的 Hook，例如模型路由、审计、企业策略。

```python
handle = host.register_hook(
    HookRegistrationRequest(
        phase="PreModelRequest",
        scope=HookRegistrationScope(lifetime=HookScopeLifetime.SESSION_TEMPLATE),
        handler=HookHandlerManifest(
            kind=HookHandlerKind.CALLBACK,
            callback=lambda _payload: {"request_override": {"requested_model": "enterprise-model"}},
        ),
        contract={"effect_fields": ["request_override", "metadata"]},
    )
)
```

`session API / turn API`

- 适合当前 session 或当前 turn 的动态注册。
- 如果你只是想快速写一个最小可运行 Hook，优先从 `session API` 开始；只有在已经进入活跃 turn 时，再使用 `turn API`。

`legacy definition compatibility`

- 旧版按 phase 分组的定义仍然可以接受，但会在激活前先被规范化。

```yaml
hooks:
  PreToolUse:
    matcher: echo
    effect:
      updated_input:
        value: rewritten
```

对于新的接入面，仍然优先推荐规范的声明式结构。

### 1.6 注册来源对比

同一套 Hook 模型可以从不同来源进入系统，区别主要在“谁拥有它”“默认生命周期是什么”“它是不是 stable public registration surface”。

| 注册来源 | 典型入口 | 默认作用范围 | 适合场景 | v1 定位 |
| --- | --- | --- | --- | --- |
| `runtime config` | `RuntimeConfig(hooks=...)` | `session-template` | 所有 session 默认生效的基础能力 | stable public |
| `host API` | `host.register_hook(...)` | `session-template` | 宿主统一挂载的企业策略、路由、审计 | stable public |
| `session API` | `session.register_hook(...)` | `session` | 某个 session 内持续生效的动态逻辑 | stable public |
| `turn API` | `session.register_hook(...)` 或 `session.register_turn_hook(...)` | `turn` | 只影响当前 turn 的一次性或短期逻辑 | advanced |
| `skill hooks` | skill frontmatter `hooks` | 通常为 `session` 或 `turn` | 随 workflow 一起打包的 hook 逻辑 | stable public |
| `legacy definition` | 旧版 `hooks.PreToolUse.matcher/effect` | 取决于加载路径 | 兼容历史 definition | compatibility-only |

选择建议：

- 想让能力默认附着到所有 session，用 `runtime config`。
- 想让宿主统一注入策略，用 `host API`。
- 想在一次会话里动态开关能力，用 `session API`。
- 想只影响当前 turn，优先用 `turn API`。
- skill / invocation definition hooks 仍然是支持中的 migration path；runtime 会先把旧定义归一化成 canonical `HookRegistrationRequest` 再激活。
- 不要把 hook 写在 agent frontmatter 里当成普通 v1 能力面；agent-owned hooks 默认会被拒绝，只有显式 legacy mode 才会重新容忍。
- 如果要审计当前 assembly 是否仍启用了这条 legacy path，可直接看 `closure_report.compatibility_retirement`。

### 1.7 Hook 注册后如何观察和诊断

这个平台不只提供注册，还提供可观测性。

`list_hooks(...)`

- 用来查看当前有哪些注册项。
- 适合确认 phase、scope、source 和 activation state 是否符合预期。

`list_hook_dispatch_traces(...)`

- 用来查看某个 phase 实际 dispatch 时发生了什么。
- 适合排查“为什么没命中”“为什么被阻断”“谁最终赢了”。

dispatch trace 里重点看这些字段：

- `matched_registrations`
- `blocked_registrations`
- `ignored_effects`
- `winner_summary`
- `applied_outcome`

如果某个 phase 返回了不支持的 effect 字段，这些字段不会静默生效，而是会被记到 `ignored_effects` 里。

### 1.8 Stop / Recovery 是平台内建的恢复控制流

`Stop` hook 可以阻断继续执行，并暂存一个可恢复的 request override。随后，`RecoveryDecision` hook 可以通过规范的恢复路径恢复执行。

```python
weavert.bind_hook_callback(
    "runtime_stop_guard",
    lambda _payload: {
        "continue_execution": False,
        "stop_disposition": "block_session",
        "request_override": {"max_output_tokens": 1024},
    },
)

session.register_hook(
    HookRegistrationRequest(
        phase="RecoveryDecision",
        handler=HookHandlerManifest(
            kind=HookHandlerKind.CALLBACK,
            callback=lambda _payload: {
                "continue_execution": True,
                "injected_messages": ["Approval received"],
            },
        ),
        contract={"effect_fields": ["continue_execution", "injected_messages", "metadata"]},
    )
)
```

这部分适合审批流、人工恢复、失败后继续执行等场景。

### 1.9 外部 Handler 默认是受限的

公开 manifest 模型仍支持 `callback`、`http`、`command`、`agent` 和 `prompt`。其中：

- `callback` 是唯一稳定 public handler kind
- `http`、`command`、`agent`、`prompt` 属于 advanced 或 package-specific surface
- 外部 handler 默认是拒绝的，必须通过 `HookBus.set_handler_policy(...)` 显式放行

```python
weavert.services.hook_bus.set_handler_policy("http", allowed=True, phase="PostToolUse")
```

当 policy 阻止外部 handler 执行时，dispatch trace 会记录一条 `blocked_registrations`，其 reason 为 `policy_denied`。

## 2. 按这份文档写一个最小可运行 Hook 的步骤

如果你的目标只是“先让一个 Hook 跑起来”，最短路径是：

1. 选择一个 stable public phase。
2. 选择 `callback` 作为 handler。
3. 在当前 `session` 上动态注册一个 `session` 级 Hook；只有在确实需要局部控制时再用 `turn` 级 advanced surface。
4. 用 `list_hooks(...)` 确认它已经激活。
5. 触发对应 phase，并用 `list_hook_dispatch_traces(...)` 查看它是否命中。

### 2.1 最小可运行示例

下面这个示例可以直接运行。它完成三件事：

- 创建一个最小 runtime 和 session。
- 注册一个在当前 session 内生效的 `PreToolUse` Hook。
- 立即用 inventory 验证注册结果。

```python
from weavert.runtime_kernel import RuntimeConfig, assemble_runtime
from weavert.hooks import (
    HookActivationState,
    HookInventoryQuery,
    block_execution,
    match_tool,
    on_pre_tool_use,
)

weavert = assemble_runtime(RuntimeConfig())
session = weavert.create_session(session_id="demo-hook-session")

handle = session.register_hook(
    on_pre_tool_use(
        lambda _payload: block_execution(),
        match=match_tool("deploy"),
        effects=(block_execution,),
    )
)

inventory = session.list_hooks(HookInventoryQuery(phase="PreToolUse"))

assert handle.activation_state == HookActivationState.ACTIVE
assert any(entry.phase == "PreToolUse" for entry in inventory)
print("hook registered:", handle.registration_id)
```

这个例子已经足够验证：

- API 形状是正确的。
- 当前 phase 是公开可注册的。
- 当前 Hook 已经被 runtime 接受并激活。

如果你需要看它底层到底展开成什么对象模型，下面 2.3 会继续给出等价的 raw `HookRegistrationRequest` 写法。

如果你还想验证“Hook 是否真的被 dispatch 并产生 effect”，继续看下面的分步流程。

下面用 `PreToolUse` 做一个最小示例。它表达的是：

- 在当前 session 中注册一个 Hook。
- 只匹配 `deploy` 这个工具。
- 当工具即将执行时，先把执行继续权改成 `False`。

### 2.2 第一步：准备 runtime 和 session

```python
from weavert.runtime_kernel import RuntimeConfig, assemble_runtime

weavert = assemble_runtime(RuntimeConfig())
session = weavert.create_session(session_id="demo-hook-session")
```

### 2.3 第二步：注册一个最小的 callback Hook

```python
from weavert.hooks import (
    HookHandlerKind,
    HookHandlerManifest,
    HookRegistrationRequest,
    HookRegistrationScope,
    HookScopeLifetime,
)

handle = session.register_hook(
    HookRegistrationRequest(
        phase="PreToolUse",
        match={"target": "deploy"},
        scope=HookRegistrationScope(
            lifetime=HookScopeLifetime.SESSION,
            session_id=session.state.session_id,
        ),
        handler=HookHandlerManifest(
            kind=HookHandlerKind.CALLBACK,
            callback=lambda _payload: {"continue_execution": False},
        ),
    )
)
```

这一步最关键的只有三件事：

- `phase="PreToolUse"`，表示在工具执行前触发。
- `match={"target": "deploy"}`，表示只匹配 `deploy`。
- `callback` 返回 `{"continue_execution": False}`，表示命中后阻断继续执行。

如果你明确要做 `turn` 级 Hook，需要在当前 session 已经进入活跃 turn 的前提下，再把 `lifetime` 改成 `HookScopeLifetime.TURN`，并补上对应的 `turn_id`。

### 2.4 第三步：确认注册已经生效

```python
from weavert.hooks import HookInventoryQuery

inventory = session.list_hooks(HookInventoryQuery(phase="PreToolUse"))
```

这里至少要确认两件事：

- `handle.activation_state` 是 `active`，而不是 `rejected`。
- inventory 里能看到这条注册项，并且 phase、scope、owner 都符合预期。

### 2.5 第四步：触发对应 phase

接下来只要让当前 session 内出现一次 `deploy` 工具调用，`PreToolUse` hook 就会在真正执行工具之前被触发。

如果 Hook 生效，runtime 会在这一阶段先消费 Hook 的 effect，再决定是否继续执行工具。

### 2.6 第五步：查看 dispatch trace

```python
from weavert.hooks import HookDispatchTraceQuery

traces = session.list_hook_dispatch_traces(
    HookDispatchTraceQuery(phase="PreToolUse", limit=20)
)
```

这里最值得看的是：

- `matched_registrations`
  用来确认是不是你的 Hook 命中了。
- `winner_summary`
  用来确认最终生效的是哪条注册项。
- `applied_outcome`
  用来确认运行时最终采纳了什么结果。
- `blocked_registrations` 和 `ignored_effects`
  用来排查是被 policy 挡了，还是 effect 字段不被当前 phase 支持。

### 2.7 如果要把最小示例升级成正式接入

当这个最小示例验证通过后，通常会往三个方向演进：

- 从 `session.register_hook(...)` 升级到 `runtime config`，把它变成默认模板 Hook。
- 从单纯的 `callback` 扩展到带 `contract` 的正式 effect 声明。
- 从单一 phase 扩展到完整控制流，例如 `Stop` + `RecoveryDecision` 组成审批恢复链路。

如果你的目标不是“先跑起来”，而是“作为平台能力长期挂载”，那就不应停留在最小示例阶段，而应该回到上面的对象模型，补全 scope、contract、policy 和 diagnostics 设计。
