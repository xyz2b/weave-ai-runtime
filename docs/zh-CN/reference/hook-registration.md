# Hook 注册参考

这页汇总公开 hook registration 周围的稳定词汇。

## 适合谁？

- 已理解整体工作流、现在需要稳定查询页的读者。

## 前置条件

- 先读对应的 guide 或 concept 页面
- 把这页当成 reference sheet，而不是第一站教程

## 稳定公开 phases

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

## 高级公开 phases

- `UserPromptSubmit`
- `SubagentStop`
- `PreCompact`
- `PostCompact`
- `PreContextAssemble`
- `PostContextAssemble`
- `RecoveryDecision`

只有当稳定集合真的不够时，再使用 advanced phases。

## 常见注册 scope

- `session-template`
  - 模板级注册，之后 materialize 到具体 sessions
- `session`
  - 在整个 session 生命周期内有效
- `turn`
  - 只在当前 turn 内短暂生效

## 公开注册层

- simple layered registrars
  - `runtime.hooks`、`bound.hooks`、`session.hooks`
- typed registration layer
  - 带 phase-aware callbacks 的显式 effect intent
- raw registration layer
  - 直接控制 canonical request

## Handler kinds

稳定公开 handler kind：

- `callback`

高级或 package-specific handler kinds 可能包括：

- `http`
- `command`
- `agent`
- `prompt`

普通集成应把 `callback` 当作可移植默认值。

## Activation-state 词汇

常见 activation states 包括：

- `pending_activation`
- `active`
- `released`
- `expired`
- `rejected`

## Inventory 与 dispatch 检查

有用的 inspection helpers 包括：

- `HookInventoryQuery`
- `HookDispatchTraceQuery`

它们帮助回答：

- 当前有哪些 registrations
- 哪些匹配成功
- 哪些 effects 被忽略
- 实际应用的结果是什么

## 下一步

- 若想看 step-by-step 编写路径，回到 `../guides/register-hooks.md`
- 如果下一步是证明某个 hook 确实匹配并正确生效，进入 `../guides/testing-and-observability.md`

## 另见

- `../guides/register-hooks.md`
- `../guides/extend-the-control-plane.md`
- `../guides/testing-and-observability.md`
- `../deep-dives/weavert-hook-configuration-platform.md`
