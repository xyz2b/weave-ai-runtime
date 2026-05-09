# 注册 Hooks

## 适合谁？

想在稳定运行时生命周期阶段注入逻辑，但又不想重写主运行时循环的用户。

## 前置条件

- 一个可运行的 runtime baseline
- 熟悉 sessions 或 bound host
- 已经明确你想拦截或观察的生命周期点

## 稳定阶段与高级阶段

普通 hook 路径应尽量停留在稳定公开 phases 上。
常见稳定 phases 包括：

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

也存在 advanced phases，但它们不是默认可移植性承诺。
只有在稳定集合确实不够时才使用它们。

## 三层编写方式

公开 hook 表面最容易按三层理解：

- simple layered registrars
  - `runtime.hooks`、`bound.hooks`、`session.hooks`
- typed layer
  - phase-aware callback + explicit effect intent
- raw layer
  - 直接控制 `HookRegistrationRequest`

先从最简单的方式开始。
只有在你确实需要更明确的 effect 或 scope 控制时，再进入 typed 或 raw registration。

## 最小 session-scoped 示例

```python
from weavert.hooks import HookDispatchTraceQuery, HookInventoryQuery, match_tool, rewrite_input

handle = session.hooks.on_pre_tool_use(
    lambda _payload: rewrite_input({"value": "rewritten"}),
    match=match_tool("echo"),
    effects=(rewrite_input,),
)

inventory = session.list_hooks(HookInventoryQuery(phase="PreToolUse"))
traces = session.list_hook_dispatch_traces(HookDispatchTraceQuery(phase="PreToolUse", limit=20))
```

如果你想先做一个小而可检查的 runtime hook，这通常是最好的第一种模式。

## 选择正确的注册来源

### Runtime-level 模板注册

适合未来每个 session 默认都应继承该 hook 的情况。

### Bound-host 注册

适合 host 想把某种策略或行为注入到它拥有的 sessions 时。
这很适合 enterprise routing、approvals 或 audit posture。

### Session 注册

适合行为只在单个 session 生命周期内有效时。

### Turn-owned 高级注册

只有当行为应仅在当前 turn 内生效时才使用。

### Skill hooks

当 hook 应跟随某个可复用 workflow step 一起移动时，使用 skill hooks。

## 如何检查与调试 hook 行为

注册后，既要验证 inventory，也要验证 dispatch：

- `list_hooks(...)`
  - 确认 phase、source、scope 和 activation state
- `list_hook_dispatch_traces(...)`
  - 确认匹配、拦截、忽略的 effects，以及最终应用结果

如果某个 hook effect 不被该 phase 支持，它应显示为 ignored，而不是假装成功。

## 什么时候不要用 agent-owned hooks

Agent-owned hooks 不是普通推荐的 v1 路径。
优先使用：

- skill hooks
- session hooks
- bound-host hooks
- runtime-config hook registration

## 预期结果

你可以通过稳定 runtime surfaces 注册、观察并调试 hook 行为。

## 下一步

运行 `python3 -B -m examples.hooks.session_register_hook_demo` 或 `python3 -B -m examples.hooks.host_registered_hook_demo`。

## 另见

- `extend-the-control-plane.md`
- `testing-and-observability.md`
- `../reference/hook-registration.md`
- `../deep-dives/weavert-hook-configuration-platform.md`
