# memory-subsystem Specification

## Purpose
TBD - created by archiving change python-agent-runtime-foundation. Update Purpose after archive.
## Requirements
### Requirement: 默认参考实现风格 memory provider
runtime SHALL 提供一个默认文件型 memory 子系统，遵循参考实现兼容的目录解析与 prompt 注入行为。

#### Scenario: 使用默认 memory 启动 session
- **WHEN** 某个 session 在启用默认 memory provider 的情况下启动
- **THEN** runtime SHALL 解析 memory 目录、加载 `MEMORY.md` 或等价入口内容，并将 memory instructions 注入 session prompt context

### Requirement: relevant memory retrieval
runtime SHALL 在 turn 执行前检索 relevant memories，并将其提供给 turn engine。

#### Scenario: 在 prompt 之前筛选相关 memories
- **WHEN** 用户提交一个 prompt
- **THEN** runtime SHALL 评估当前可用的已存储 memories，并在模型执行前把判定为相关的 memories 注入 turn context

### Requirement: turn 后 memory 提取
runtime SHALL 支持在主线程 session 中使用默认 memory provider 自动执行 post-turn memory extraction。

#### Scenario: 主线程 turn 结束但未直接写 memory
- **WHEN** 主线程 agent 完成一个 turn，且尚未直接写入相关的 memory update
- **THEN** runtime SHALL 执行配置好的 post-turn extraction flow，并通过默认 provider 持久化提取出的 memory updates

### Requirement: agent memory scopes
runtime SHALL 支持与参考实现风格一致的 agent-specific memory scopes，包括 user、project 与 local memory 行为。

#### Scenario: agent 使用 project scope memory
- **WHEN** 某个 agent definition 声明了 project-scoped memory 配置
- **THEN** runtime SHALL 在 project-scoped memory 边界内加载并持久化该 agent 的 memory，而不是落到 user-wide 边界

### Requirement: Memory remains an official first-party runtime capability
The supported first-party `runtime-default` and `runtime-full` distributions SHALL include the first-party memory capability package, and SHALL keep memory as an official first-party runtime capability even when its implementation is packaged outside `runtime-core`.

#### Scenario: `runtime-default` boots with first-party memory
- **WHEN** `runtime-default` is assembled
- **THEN** the runtime SHALL register the first-party memory subsystem without requiring the embedder to discover or wire a separate third-party package
- **AND** SHALL expose memory through the same runtime-owned contracts used by the rest of the runtime

#### Scenario: `runtime-core` remains bootable without the memory package
- **WHEN** an embedder assembles `runtime-core` without the official first-party memory package
- **THEN** the runtime SHALL still boot under the core runtime contract
- **AND** SHALL treat the missing memory package as an explicit capability-selection choice rather than as a kernel bootstrap error

### Requirement: Kernel-memory integration uses explicit package boundaries
The runtime SHALL consume memory through explicit provider, manager, and context-contribution contracts rather than through hard package-layout assumptions inside kernel-only modules.

#### Scenario: first-party memory package is wired during runtime assembly
- **WHEN** the official memory package is present during runtime assembly
- **THEN** the runtime SHALL attach memory-owned services and hooks through explicit assembly wiring
- **AND** SHALL keep the kernel-side integration limited to published runtime service and context contribution contracts

#### Scenario: memory implementation moves without changing the kernel contract
- **WHEN** the first-party memory implementation moves to a different first-party package boundary
- **THEN** the runtime SHALL preserve the same runtime-owned memory contracts for retrieval, post-turn extraction, and memory-scope behavior
- **AND** SHALL NOT require embedders to rewrite kernel-facing integration code solely because of the package move

### Requirement: Background memory work SHALL project through the shared job control plane
runtime SHALL register background memory extraction and consolidation work in the shared job control plane while preserving memory-specific queue and synthesis semantics.

#### Scenario: runtime schedules background memory extraction
- **WHEN** runtime schedules a background memory extraction pass for a session, agent, or scope
- **THEN** it SHALL create or update a shared job record for that background memory work
- **AND** SHALL keep memory-specific batching, merge, or extraction metadata in memory-owned sidecar state rather than flattening them into the generic job schema

#### Scenario: background memory work reaches a terminal state
- **WHEN** a background memory extraction or consolidation run completes, fails, or is stopped
- **THEN** runtime SHALL update the corresponding shared job record with the resulting lifecycle state
- **AND** SHALL preserve any memory-specific output or diagnostics through the memory subsystem's own result path or sidecar linkage

