## Why

long-context compaction 是参考实现抽象里最容易被低估、但最像 runtime 核心的部分。当前 runtime 还没有显式的 compaction control plane，这意味着长会话只能依赖零散截断或外部手工压缩，无法形成参考实现风格的 continuation semantics。

## What Changes

- 引入统一的 `CompactionManager`，把 long-context reduction、boundary semantics 与 continuation handling 提升为 runtime 的一等控制面。
- 在 provider request 前把 compaction 纳入 turn preparation，而不是散落在 request helper 或 prompt truncation 逻辑中。
- 让 compaction 产出结构化结果，覆盖 compacted messages、summaries、boundary metadata 与 resume-safe continuation。
- 通过 ordered strategy contract 为后续多阶段 compaction 策略预留稳定接口，同时在第一阶段优先收敛 orchestration contract。

## Capabilities

### New Capabilities

- `runtime-compaction-manager`: 定义 long-context compaction control plane，包括 compaction orchestration、boundary semantics 与 resume-safe continuation。

### Modified Capabilities

## Impact

- 影响 `src/runtime/compaction/`、`src/runtime/session_runtime/`、`src/runtime/turn_engine/`、transcript flow 与上下文装配。
- 会把当前隐式 context truncation 升级为真正的 runtime control plane。
- 为长会话、resume、background continuation 与 future compact hooks 提供稳定边界。
