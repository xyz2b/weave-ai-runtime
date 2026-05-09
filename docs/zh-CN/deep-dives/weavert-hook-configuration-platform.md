# WeaveRT Hook 配置平台

> 文档说明：这是 hook registration model 的 deep-dive 参考。普通路径请先读 `docs/zh-CN/guides/register-hooks.md` 与 `docs/zh-CN/reference/hook-registration.md`。

## 对应主文档

- Hook authoring -> `docs/zh-CN/guides/register-hooks.md`
- Hook quick reference -> `docs/zh-CN/reference/hook-registration.md`
- Control-plane overview -> `docs/zh-CN/guides/extend-the-control-plane.md`

## 1. 平台是什么

Hook 平台用于：

- 拦截 tool execution
- 塑造 request context 或 model routing
- 挂接 approval 或 recovery logic
- 发出 audit 或 lifecycle observations
- 让可复用 hook 行为穿过 runtime、host、session 或 skill 表面

## 2. 公开 phase 模型

- 优先停留在稳定公开 phases
- 只有在稳定集合不够时，再进入 advanced phases

## 3. 注册模型

一个重要规则是：不受支持的 effect 字段应被忽略，而不是被当成成功；这些 ignored effects 还应出现在 diagnostics 中。

## 4. 编写层次

- 先从 simple surface 开始
- 当你需要显式 effect declaration 时，再切到 `.typed`
- 只有需要精确低层控制 scope、contract 或 handler manifest 时，才进入 `.raw`

`activation_state` 用于说明当前是 `pending`、`active`、`released`、`expired` 还是 `rejected`。
`release()` 应保持幂等。

## 5. 注册来源

- `bound.hooks...` 默认先挂到 template layer，而不是立即注入到所有现有 sessions
- skill hooks 仍是成熟的 definition-level hook 路径
- agent-owned hooks 不是普通 v1 路径，默认 assembly 会拒绝它们

## 6. 匹配、诊断与调试

主要检查方式：

- `list_hooks(...)`
- `list_hook_dispatch_traces(...)`

关注字段：

- `matched_registrations`
- `blocked_registrations`
- `ignored_effects`
- `winner_summary`
- `applied_outcome`

## 7. Recovery 与策略边界

### 7.1 Stop / recovery 属于正式 control flow

- approval gating
- continue-after-failure flows
- manual recovery decisions
- stop-and-resume control paths

### 7.2 External handlers 默认受限

- `callback` 是唯一稳定的公开默认值
- `http`、`command`、`agent` 与 `prompt` 不是普通安全默认值
- external handlers 需要显式 handler policy allowance

## 8. 第一次集成时该用什么

- 第一条工作示例 -> `docs/zh-CN/guides/register-hooks.md`
- 紧凑查询页 -> `docs/zh-CN/reference/hook-registration.md`
- 更宽的 host / permission 上下文 -> `docs/zh-CN/guides/extend-the-control-plane.md`

## 9. 相关文档

- `docs/zh-CN/guides/register-hooks.md`
- `docs/zh-CN/reference/hook-registration.md`
- `docs/zh-CN/guides/extend-the-control-plane.md`
- `docs/zh-CN/deep-dives/weavert-control-plane-extension-guide.md`
