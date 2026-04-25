## ADDED Requirements

### Requirement: Teammate orchestration remains an official first-party runtime capability
The supported first-party `runtime-default` and `runtime-full` distributions SHALL include the first-party team and teammate orchestration capability package, and SHALL keep that capability official even when its implementation is packaged outside `runtime-core`.

#### Scenario: `runtime-default` boots with team capability
- **WHEN** `runtime-default` is assembled
- **THEN** the runtime SHALL register the first-party team control and teammate orchestration capability without requiring the embedder to discover a separate third-party package
- **AND** SHALL preserve the same runtime-owned contracts for team lifecycle, message routing, and teammate execution reuse

#### Scenario: `runtime-core` remains bootable without the team package
- **WHEN** an embedder assembles `runtime-core` without the official first-party team package
- **THEN** the runtime SHALL still boot under the core runtime contract
- **AND** SHALL treat the absence of the team package as an explicit capability-selection choice rather than as a kernel bootstrap error

### Requirement: Team capability packages integrate through explicit runtime contracts
The runtime SHALL integrate first-party team control, teammate orchestration, and related built-ins through explicit runtime service and assembly contracts rather than through private kernel-only package assumptions.

#### Scenario: first-party team package is installed
- **WHEN** the official team capability package is present during runtime assembly
- **THEN** the runtime SHALL attach team control planes, message buses, teammate orchestration services, and related built-ins through explicit assembly wiring
- **AND** SHALL preserve host-facing, execution-facing, and observability-facing contracts regardless of package layout

#### Scenario: teammate execution continues to reuse shared execution contracts
- **WHEN** the first-party team package is installed from outside the `runtime-core` package boundary
- **THEN** teammate execution SHALL still reuse the shared execution core, permission bridge, and lifecycle projection contracts already defined by the runtime
- **AND** SHALL NOT introduce a second kernel-private execution engine just because the package boundary changed
