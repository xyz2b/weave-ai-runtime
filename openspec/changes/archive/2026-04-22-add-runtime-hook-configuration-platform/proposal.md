## Why

当前 runtime 已经有 `HookBus`、phase payload 和结构化 `HookEffect`，但这些能力仍然更像内核预留位和 skill-owned hook 机制，还没有形成一套面向框架接入方的完整 hook 配置平台。宿主和业务方目前缺少稳定的方式在 runtime 主循环中注册自己的审批、审计、路由、上下文整形、恢复决策和外部协同逻辑，只能依赖局部 wiring、definition-specific 约定或直接改 runtime 主循环。

现在需要把现有 hook 机制提升为正式的 runtime extension surface：既保持 runtime kernel 对 phase、payload、aggregation 和 ownership 的控制，又让接入方能通过配置和编程接口把业务逻辑稳定注入到 session、turn、tool、subagent 和 control-plane 生命周期中。这会决定后续 runtime 是否能作为可嵌入框架，而不只是当前仓库自己的参考实现。

## What Changes

- 引入面向 runtime framework 的 hook 配置平台，明确 hook 的公开目标不是 CLI 自动化，而是向宿主和业务方暴露稳定的 runtime 注入点。
- 定义 hook 的多层注册与配置面，覆盖 runtime-level、host-level、agent/skill-owned 和 session-scoped dynamic registration，而不是只依赖 skill frontmatter。
- 定义 hook 的 canonical authoring schema，区分 declarative authoring envelope、normalized runtime registration 和 active bus entry，使 runtime config、definition frontmatter、host API、session API 与 turn API 最终收敛到同一模型。
- 定义 hook handler 的执行适配器契约，覆盖 in-process callback、HTTP、subprocess command、delegated agent 和 prompt-style handler，并明确各自的输入、超时、失败、隔离和 observability 语义。
- 定义 handler adapter manifest 与 callback binding contract，避免 declarative config 直接依赖 raw callable、临时 transport blob 或实现细节字段。
- 为 runtime 主循环补齐 framework-oriented 的稳定 hookable decision points，除现有 session/tool/stop/elicitation/compact phase 外，还要覆盖 context assembly、model request shaping、post-response handling 和 recovery decision 等关键边界。
- 发布一份 authoritative hook phase catalog，明确首批 `kernel public` 与 `control-plane public` phase 名单，以及未列入 catalog 的 phase 默认属于 `internal-only`。
- 区分 hook phase 的稳定性层级，明确哪些 phase 是 public kernel contract，哪些是 control-plane contract，哪些仍然是 internal implementation detail，避免接入方把临时内部节点当作长期 authoring surface。
- 扩展 hook aggregation contract，使多个 hooks 同时命中时，对 observe、transform、decide 和 sidecar 类型效果具有确定性顺序、冲突裁决和 scope-aware cleanup，而不是继续依赖偶然执行顺序。
- 定义跨 runtime config、host API、definition、session API 和 turn API 的 precedence ladder、materialization order 与 winner attribution，明确多来源 hook 命中时谁先执行、谁能覆盖谁、宿主如何解释最终生效结果。
- 为 hook 平台增加 policy、trust 和 diagnostics contract，明确哪些 handler 允许执行外部逻辑、哪些只允许内存内回调，以及宿主如何看到 matched hooks、effective overrides、failure mode 和 side effects。
- 发布 host-visible diagnostics schema，覆盖 registration inventory、phase dispatch trace、field-level winner attribution、blocked/timeout/ignored reason 和 terminal correlation，避免每个 phase 各自暴露不一致的调试字段。
- 定义对称的 public hook APIs，覆盖 runtime-level template registration、host delegation、session/turn registration、registration handle lifecycle，以及 inventory/dispatch-trace inspection 接口。

## Capabilities

### New Capabilities

- `runtime-hook-configuration-platform`: 定义面向框架接入方的 hook 配置与注册平台，覆盖注册来源、ownership/scope、handler kinds、stability tiers、policy/trust gate 和诊断暴露。

### Modified Capabilities

- `hook-system`: 从“参考实现兼容 phase 名称”扩展为“framework-oriented hook lifecycle contract”，明确 public kernel phases、control-plane phases 与 internal-only phases 的边界。
- `runtime-hook-bus`: 从基础 phase dispatch / effect aggregation 扩展为支持配置化 handler、typed execution class、deterministic merge 和 scope-aware cleanup 的正式平台契约。
- `runtime-main-loop-state-machine`: 增补 context assembly、request shaping、response handling 与 recovery decision 的稳定 hook points，使业务逻辑可以在不改主循环的前提下注入这些关键路径。

## Impact

- 影响 `src/runtime/hooks/`、`src/runtime/runtime_services/`、`src/runtime/turn_engine/`、`src/runtime/session_runtime/`、`src/runtime/tool_runtime.py`、`src/runtime/agent_execution_service.py`、`src/runtime/skill_runtime.py` 与 host/control-plane binding。
- 影响 hook authoring surface、definition loading、dynamic registration、policy enforcement、diagnostics metadata 和 host-visible observability。
- 影响 runtime config / frontmatter schema、host/session/turn registration APIs、handler binding resolution 和 definition compatibility loading。
- 影响 runtime/host/session public APIs、registration handle semantics、dispatch-trace retention/query and close-time cleanup behavior。
- 会为后续 approval workflow、audit/compliance、custom routing、memory/context sidecars、human-in-the-loop decision 和 enterprise integration 提供统一扩展边界。
