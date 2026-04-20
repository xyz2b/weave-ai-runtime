## Why

当前 Python runtime 已经具备可运行的 execution plane，但 control plane 仍然散落在零散 callback、占位类型和局部 wiring 中，无法稳定承接参考实现里的 hooks、permissions、elicitation、memory、compaction 与 host bridge。要让抽象出的 runtime framework 真正与参考实现的主要框架对齐，必须先补出统一的 control-plane spine。

## What Changes

- 引入统一的 runtime control-plane spine，定义并装配 `RuntimeServices`、`RuntimeKernel` 与各子系统之间的稳定依赖边界。
- 将现有 callback 式 runtime wiring 收敛到显式服务对象，覆盖 hooks、permissions、elicitation、memory、compaction、host runtime、transcript 与 task 等控制面能力。
- 重构 kernel、session、turn engine、tool runtime、agent runtime、skill runtime 之间的装配关系，使 control plane 与 execution plane 分层明确。
- 把 prompt/context 装配提升为 control-plane aware 的上下文装配流程，为后续 memory、hook、compaction 注入留出稳定接口。

## Capabilities

### New Capabilities
- `runtime-control-plane-spine`: 定义 runtime control plane 的核心服务图、装配顺序、依赖方向与生命周期契约。

### Modified Capabilities

## Impact

- 影响 `src/runtime/runtime_kernel/`、`src/runtime/turn_engine/`、`src/runtime/session_runtime/`、`src/runtime/tool_runtime.py`、`src/runtime/agent_runtime.py`、`src/runtime/skill_runtime.py`。
- 需要新增 runtime services 与 control-plane 相关的模块边界，但不直接引入新的产品层 UI 逻辑。
- 为后续 hooks、permissions、host、memory、compaction 的 follow-up 变更提供统一装配基础。
