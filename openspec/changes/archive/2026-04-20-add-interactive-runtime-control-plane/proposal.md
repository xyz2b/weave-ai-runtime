## Why

当前 runtime 还没有形成参考实现风格的 interactive control plane。没有统一的 `HookBus`、`HostAdapter`/`HostRuntime` bridge、`PermissionEngine` 与 `ElicitationService`，CLI、UI、SDK 只能在 runtime 外面各自包一层 while loop，无法共享同一套 session control 与 runtime routing 语义。

## What Changes

- 引入 interactive runtime control plane，把 `HookBus`、`PermissionEngine`、`ElicitationService` 与 `HostRuntime`/`HostAdapter` bridge 作为同一阶段能力落地。
- 让 session、turn、tool、skill、subagent execution 统一经过 shared hook dispatch、permission evaluation 与 elicitation flow，而不是继续依赖局部 callback。
- 将 permission prompt、`ask_user`、notifications、turn events 与 host lifecycle 统一通过 host bridge 暴露，使 CLI、SDK 与未来 UI 共享同一套 runtime stack。
- 提供最小 CLI host 与 SDK host reference implementations，验证 interactive 与 headless 场景复用同一 `SessionController` 与 `TurnEngine`。

## Capabilities

### New Capabilities

- `runtime-hook-bus`: 定义参考实现兼容 runtime hooks 的 phase dispatch、matcher、effect 聚合与 session-scoped ownership。
- `permission-and-elicitation-control-plane`: 定义统一的 permission 与 elicitation 决策流，覆盖 tool、skill 与 subagent execution。
- `host-runtime-bridge`: 定义 runtime 与 host adapter 之间的桥接契约，覆盖 lifecycle、permission、elicitation、notification 与 turn events。

### Modified Capabilities

## Impact

- 影响 `src/runtime/hooks/`、`src/runtime/permissions/`、`src/runtime/elicitation/`、`src/runtime/hosts/`、`src/runtime/session_runtime/`、`src/runtime/turn_engine/`、`src/runtime/tool_runtime.py`、`src/runtime/skill_runtime.py` 与 runtime assembly。
- 会替换现有的 `check_permissions`、`permission_handler`、`ask_user_handler`、host lifecycle callback 等零散 wiring。
- 为后续参考实现风格 memory、long-context compaction 与 skill policy/isolation 提供 interactive runtime 骨架。
