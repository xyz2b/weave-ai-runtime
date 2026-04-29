## ADDED Requirements

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
