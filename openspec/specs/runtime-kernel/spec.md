# runtime-kernel Specification

## Purpose
TBD - created by archiving change python-agent-runtime-foundation. Update Purpose after archive.
## Requirements
### Requirement: Python runtime kernel 引导
runtime SHALL 提供一个 Python runtime kernel，用于从 bundled 和用户提供的 runtime definitions 引导 configuration、registries、persistence wiring 与默认子系统。

#### Scenario: 使用 bundled 与用户定义启动 kernel
- **WHEN** runtime 在 bundled definitions 与引用了 custom tools、agents、skills、memory settings 和 hooks 的用户配置下启动
- **THEN** runtime SHALL 在任何 conversation session 开始前构建对应的 registries 与 subsystem instances

### Requirement: 显式 session controller
runtime SHALL 暴露一个 `SessionController`，在 turn execution 开始前将来自 host 的输入事件归一化到单一的 session command flow 中。

#### Scenario: 不同 hosts 共享一套 session flow
- **WHEN** 一个 CLI host 与一个 SDK host 分别向同一 runtime contract 提交用户 prompt
- **THEN** runtime SHALL 通过同一套 session command lifecycle 归一化两类输入，而不是依赖 host-specific control logic

### Requirement: 与 host 无关的 turn engine
runtime SHALL 通过一个与 host 无关的 turn engine 执行 conversational turns，该 turn engine 必须能够同时复用于 interactive 与 headless hosts。

#### Scenario: turn engine 不依赖 UI 所有权
- **WHEN** 某个 host adapter 启动一个新的 turn
- **THEN** runtime SHALL 通过 turn engine 处理 prompt composition、model interaction、tool orchestration 与 turn completion，而不要求 host 自己实现这些行为

### Requirement: Kernel SHALL assemble selected official packages through manifest-driven dependency ordering
The runtime kernel SHALL assemble selected official first-party packages through manifest-driven dependency ordering and package contributions rather than relying on package-name-specific attachment logic as the primary official package integration mechanism.

#### Scenario: Assembling a runtime with several official packages
- **WHEN** the runtime kernel assembles a runtime that selects multiple official first-party packages
- **THEN** it SHALL resolve package dependency ordering from package manifests before applying package contributions
- **AND** it SHALL apply those packages through the shared package assembly path rather than requiring one custom kernel branch per package as the primary attachment contract

### Requirement: Kernel SHALL preserve the runnable core skeleton independent of optional package presence
The runtime kernel SHALL preserve the existing runnable kernel/session/turn skeleton when optional official packages are absent, while still allowing selected packages to contribute additional capabilities through the shared package integration contract.

#### Scenario: Runtime boots with only runtime-core-selected behavior
- **WHEN** the runtime assembles only the minimal core distribution or omits optional first-party packages
- **THEN** it SHALL still construct the kernel, session, and turn execution skeleton required for a runnable runtime
- **AND** optional package contribution points SHALL remain additive rather than a prerequisite for the core execution stack to exist

### Requirement: Kernel package assembly SHALL merge admitted external manifests with selected first-party manifests
The runtime kernel SHALL resolve the selected first-party package set from distribution defaults and explicit package toggles, then merge any admitted external package manifests into that set before package ordering and package contribution assembly run.

#### Scenario: admitted external package depends on a selected first-party package
- **WHEN** the selected distribution includes `runtime-core` and the caller registers an external manifest that depends on `runtime-core`
- **THEN** the kernel SHALL include the admitted external manifest in the merged package set
- **AND** SHALL order that merged set through the same dependency-ordering path used for first-party packages

### Requirement: Registration rejection SHALL happen before package contribution assembly
The runtime kernel SHALL surface package-registration diagnostics and exclude rejected external manifests before built-in, services, runtime, lifecycle, or host-facet package contributions are applied.

#### Scenario: rejected external manifest is excluded from assembly
- **WHEN** an external manifest is rejected during registration validation
- **THEN** the kernel SHALL record the rejection diagnostic before package assembly continues
- **AND** SHALL NOT call that rejected manifest's assembly entrypoint for any package assembly stage

### Requirement: Kernel package assembly SHALL resolve a manifest graph before contribution assembly
The runtime kernel SHALL build a local package candidate catalog from official first-party manifests and admitted external registrations, apply distribution defaults and explicit package requests to that catalog, and resolve a concrete manifest graph before dependency ordering and package contribution assembly begin.

#### Scenario: kernel resolves a graph that includes an external candidate
- **WHEN** the selected runtime includes official first-party packages and the admitted external registration set adds another package candidate
- **THEN** the kernel SHALL resolve the combined candidate graph before package contribution assembly
- **AND** SHALL hand only the selected manifest graph to the downstream dependency-ordering path

### Requirement: Resolution failures SHALL block package contribution assembly deterministically
The runtime kernel SHALL surface package-resolution diagnostics before package contribution assembly and SHALL NOT proceed into services or runtime package assembly when the requested package graph cannot be resolved.

#### Scenario: conflicting package constraints block assembly
- **WHEN** package resolution fails because the candidate catalog cannot satisfy all requested package constraints
- **THEN** the kernel SHALL emit structured resolution diagnostics for that runtime instance
- **AND** SHALL stop before invoking package contribution assembly for an unresolved graph

### Requirement: Kernel package selection SHALL consume the official package catalog provider
The runtime kernel SHALL consume the official package catalog provider when selecting and assembling official first-party packages rather than relying on package-name-specific kernel assembly branch tables as the canonical package-selection contract.

#### Scenario: kernel assembles selected official packages
- **WHEN** the runtime kernel selects official first-party packages for assembly
- **THEN** it SHALL resolve those packages through the official package catalog provider
- **AND** SHALL NOT require package-name-specific kernel assembly branch tables to remain the canonical package-selection contract

### Requirement: Runtime kernel default discovery roots SHALL use the WeaveRT workspace contract
The runtime SHALL use the WeaveRT workspace contract for its canonical default user and project discovery roots. `RuntimeConfig.for_project(...)` and equivalent default discovery behavior SHALL treat `~/.weavert` and `<project>/.weavert` as the canonical user-visible roots for tools, agents, skills, memory, and other discovered runtime assets.

#### Scenario: Caller uses default project bootstrap
- **WHEN** a caller constructs runtime configuration through the default project bootstrap path
- **THEN** the runtime SHALL resolve the canonical user root as `~/.weavert`
- **AND** it SHALL resolve the canonical project root as `<project>/.weavert`

### Requirement: Runtime kernel public bootstrap examples SHALL use the WeaveRT import root
The runtime SHALL expose `weavert` as the canonical public Python import root for kernel and assembly bootstrap APIs used by framework embedders.

#### Scenario: Embedder imports the runtime bootstrap API
- **WHEN** an embedder follows the canonical public bootstrap contract for creating runtime configuration or assembling the runtime
- **THEN** the public import root SHALL be `weavert`
- **AND** the runtime SHALL NOT require the embedder to import those APIs through `runtime` as the primary documented contract

