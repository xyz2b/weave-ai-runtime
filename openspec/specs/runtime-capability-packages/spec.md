# runtime-capability-packages Specification

## Purpose
TBD - created by archiving change converge-runtime-core-capability-boundaries. Update Purpose after archive.
## Requirements
### Requirement: Runtime publishes official package roles and supported distributions
The runtime SHALL define official package roles for `runtime-core`, first-party capability packages, and higher-level supported distributions, rather than treating the entire first-party product as one inseparable kernel package.

#### Scenario: embedder assembles `runtime-core`
- **WHEN** an embedder installs or assembles only `runtime-core`
- **THEN** the runtime SHALL expose the kernel, session, turn, host, registry, and stable extension contracts needed to boot a runnable runtime
- **AND** SHALL NOT require the memory or team implementation code to live in the same package as the kernel in order for `runtime-core` to be conformant

#### Scenario: embedder assembles `runtime-default`
- **WHEN** an embedder installs or assembles `runtime-default`
- **THEN** the runtime SHALL include `runtime-core` together with the official first-party memory and team capability packages
- **AND** SHALL keep that assembled distribution runnable without requiring private package mutation or undocumented bootstrap steps

### Requirement: `runtime-core` remains directly runnable
`runtime-core` SHALL remain able to boot a runnable root session through a core built-in contract that includes `main-router`.

#### Scenario: `runtime-core` boots without workspace-oriented packs
- **WHEN** `runtime-core` starts without optional workspace or devtools packs installed
- **THEN** the runtime SHALL still register `main-router` and the minimum built-ins needed for root-agent routing and runtime control
- **AND** SHALL NOT require file, shell, or web-oriented tool packs just to start a root session

#### Scenario: embedder replaces the core `main-router`
- **WHEN** an embedder replaces the bundled `main-router` definition through the documented built-in replacement contract
- **THEN** `runtime-core` SHALL honor that replacement without requiring the embedder to patch kernel internals
- **AND** SHALL continue to treat the resulting agent as the root-agent boot path under the same runtime-owned contract

### Requirement: Official capability packages integrate through explicit assembly contracts
Official first-party capability packages SHALL register their services, built-ins, and control-plane integrations through explicit runtime assembly contracts rather than through private kernel-only import assumptions.

#### Scenario: memory capability package is installed
- **WHEN** the official first-party memory capability package is present during runtime assembly
- **THEN** the runtime SHALL attach memory-owned services, built-ins, and context contribution hooks through explicit runtime assembly wiring
- **AND** SHALL NOT require memory-specific implementation code to be hard-wired into kernel-only module boundaries

#### Scenario: team capability package is installed
- **WHEN** the official first-party team capability package is present during runtime assembly
- **THEN** the runtime SHALL attach team control, teammate orchestration, and related built-ins through explicit runtime assembly wiring
- **AND** SHALL preserve the same runtime-owned contracts for host integration, execution reuse, and observability regardless of package layout

### Requirement: Runtime classifies first-party packages by role
The runtime SHALL classify official first-party packages by role rather than treating every official module as the same kind of extension. The supported first-party role taxonomy SHALL include capability packages, mechanism packages, adapter packages, and profile/workflow packages.

#### Scenario: first-party mechanism package is assembled
- **WHEN** an embedder assembles an official first-party mechanism package such as `runtime-compaction` or `runtime-isolation`
- **THEN** the runtime SHALL integrate that package through the published kernel-facing contracts for compaction or isolation
- **AND** SHALL NOT require that package to redefine the kernel's prompt/private context carriers, context-window contract, or isolation lease contract

#### Scenario: first-party adapter package is assembled
- **WHEN** an embedder assembles an official first-party adapter package such as `runtime-hosts-reference` or `runtime-stores-file`
- **THEN** the runtime SHALL allow that package to provide official implementations of replaceable host or store protocols
- **AND** SHALL keep those implementations substitutable through the same runtime-owned interfaces used by other host or store implementations

#### Scenario: first-party workflow package is assembled
- **WHEN** an embedder assembles an official first-party workflow package such as `runtime-builtin-workflows`
- **THEN** the runtime SHALL expose those workflow skills through the ordinary skill discovery and activation contracts
- **AND** SHALL NOT require those workflows to be bundled into `runtime-core` just to keep the root runtime bootable

### Requirement: First-party package dependency rules are explicit
The runtime SHALL publish and follow explicit dependency rules for first-party packages. `runtime-core` SHALL own the kernel contracts and SHALL NOT require first-party capability, mechanism, adapter, or profile/workflow packages to live inside the same package boundary. Those first-party packages SHALL depend on `runtime-core`, and higher-level supported distributions MAY assemble them together.

#### Scenario: first-party package depends on `runtime-core`
- **WHEN** an official first-party package such as `runtime-memory`, `runtime-team`, `runtime-compaction`, `runtime-isolation`, `runtime-hosts-reference`, `runtime-stores-file`, or `runtime-builtin-workflows` is assembled
- **THEN** that package SHALL depend on `runtime-core` for kernel contracts and assembly seams
- **AND** `runtime-core` SHALL remain conformant without taking a mandatory package-layout dependency on that package

#### Scenario: `runtime-full` assembles official package sets
- **WHEN** an embedder assembles `runtime-full`
- **THEN** the runtime SHALL be allowed to compose capability, mechanism, adapter, and profile/workflow packages into one supported distribution
- **AND** SHALL preserve the same runtime-owned contracts regardless of whether those modules are installed independently or through the full distribution

### Requirement: Secondary first-party packages preserve narrow kernel-facing contracts
The runtime SHALL define narrow kernel-facing contracts for official mechanism, adapter, and workflow packages so those packages can move outside `runtime-core` without redefining kernel ownership boundaries.

#### Scenario: compaction package is extracted
- **WHEN** the official `runtime-compaction` package is assembled from outside the `runtime-core` package boundary
- **THEN** the runtime SHALL keep compaction strategy and manager implementation in that package
- **AND** SHALL keep prompt/private context carriers, context-window contracts, and the turn-level compaction slot in `runtime-core`

#### Scenario: isolation package is extracted
- **WHEN** the official `runtime-isolation` package is assembled from outside the `runtime-core` package boundary
- **THEN** the runtime SHALL keep environment-specific isolation adapters in that package
- **AND** SHALL keep `IsolationMode`, isolation lease contracts, and execution assembly seams in `runtime-core`

#### Scenario: reference-host and file-store packages are extracted
- **WHEN** the official `runtime-hosts-reference` or `runtime-stores-file` package is assembled from outside the `runtime-core` package boundary
- **THEN** the runtime SHALL keep example host implementations or file-backed store implementations in those packages
- **AND** SHALL keep host protocols, bound-host semantics, store protocols, and store injection seams in `runtime-core`

#### Scenario: workflow package is extracted
- **WHEN** the official `runtime-builtin-workflows` package is assembled from outside the `runtime-core` package boundary
- **THEN** the runtime SHALL expose those workflow skills through the ordinary skill discovery and activation contracts
- **AND** SHALL keep the skill contract and executor ownership in `runtime-core`

### Requirement: Supported distributions publish stable composition semantics
The runtime SHALL publish stable composition semantics for supported assembled distributions rather than leaving first-party package composition implicit.

#### Scenario: minimal core distribution is assembled
- **WHEN** an embedder assembles the minimal `runtime-core` distribution
- **THEN** the runtime SHALL expose a runnable kernel with the root-agent boot path
- **AND** SHALL NOT require first-party capability, mechanism, adapter, or workflow packages to be present for the core distribution to remain conformant

#### Scenario: `runtime-default` is assembled
- **WHEN** an embedder assembles `runtime-default`
- **THEN** the runtime SHALL include `runtime-core` together with the first-party capability packages that define the supported product identity
- **AND** SHALL document that package set explicitly rather than leaving it as an implementation detail

#### Scenario: `runtime-full` is assembled
- **WHEN** an embedder assembles `runtime-full`
- **THEN** the runtime SHALL allow capability, mechanism, adapter, provider, and workflow packages to be composed into that supported distribution
- **AND** SHALL preserve the same runtime-owned contracts as when those packages are installed individually

#### Scenario: supported distribution names are stable
- **WHEN** an embedder reads the first-party package and distribution contract for this runtime version
- **THEN** the runtime SHALL publish the supported distribution names as `runtime-core`, `runtime-default`, and `runtime-full`
- **AND** SHALL NOT leave the middle supported distribution unnamed or implementation-defined

### Requirement: Workspace-oriented built-ins belong to higher-level supported distributions
Workspace-, file-, shell-, and web-oriented first-party built-ins SHALL be allowed to ship outside `runtime-core` while remaining available through an official higher-level supported distribution.

#### Scenario: `runtime-full` is assembled
- **WHEN** an embedder installs or assembles `runtime-full`
- **THEN** the runtime SHALL expose the core built-in contract together with the installed first-party workspace-oriented packs
- **AND** SHALL keep those definitions under the same built-in discovery, replacement, and visibility rules as other first-party built-ins

