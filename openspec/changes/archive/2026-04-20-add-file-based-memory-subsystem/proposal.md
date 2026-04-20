## Why

当前 runtime 还没有参考实现风格的 memory subsystem。目标不是“有个 memory”，而是把参考实现默认的文件型 memory 语义直接补成 runtime 的一等能力，包括 `MEMORY.md`、scope 解析、relevant retrieval 与 post-turn extraction。

## What Changes

- 引入参考实现风格的 `MemoryManager` 与默认文件型 `MemoryProvider`，而不是抽象成通用 KV store。
- 按参考实现默认语义实现 memory path resolution、`MEMORY.md` entrypoint loading、pre-turn retrieval、post-turn extraction 与 `user/project/local` scopes。
- 将 memory fragments 接入统一上下文装配与 session lifecycle，而不是依赖外部手工 prompt injection。
- 第一阶段保持默认参考实现风格行为优先，不提前开放复杂的可插拔 backend 市场。

## Capabilities

### New Capabilities

- `runtime-memory-manager`: 定义参考实现风格 memory control plane，包括 entrypoint loading、relevant retrieval、post-turn extraction 与 scope semantics。

### Modified Capabilities

## Impact

- 影响 `src/runtime/memory/`、`src/runtime/session_runtime/`、`src/runtime/turn_engine/`、上下文装配流程与 memory 相关 built-ins。
- 会把当前占位 memory 模型升级为真正的 runtime subsystem。
- 为后续 long-context compaction、resume 与 long-running sessions 提供稳定前提。
