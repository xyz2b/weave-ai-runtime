# query-runtime-assembly Specification

## Purpose
TBD - created by archiving change assemble-runnable-query-runtime. Update Purpose after archive.
## Requirements
### Requirement: Runtime assembly constructs a runnable query stack
The runtime SHALL provide an assembly layer that constructs a runnable query stack from kernel configuration, including turn execution, agent orchestration, skill execution, session control, and transcript persistence.

#### Scenario: Host obtains a runnable session from assembled runtime
- **WHEN** a host binds to the runtime using runtime configuration and bundled definitions
- **THEN** the runtime SHALL provide a runnable session surface backed by an assembled turn engine, agent runtime, skill executor, and transcript store

### Requirement: Model-generated agent and skill tool calls execute through assembled runtimes
The runtime SHALL wire built-in `agent` and `skill` tool execution through the assembled `AgentRuntime` and `SkillExecutor`, rather than requiring ad hoc caller-provided runners.

#### Scenario: Model-generated agent tool delegates successfully
- **WHEN** the model emits a built-in `agent` tool call during a turn
- **THEN** the runtime SHALL invoke the assembled subagent execution path instead of failing due to a missing agent runner

### Requirement: Session execution is host-independent
The runtime SHALL expose a session execution surface that interactive and headless hosts can share without reimplementing turn orchestration.

#### Scenario: Interactive and headless hosts share the same turn stack
- **WHEN** an interactive host and a headless host submit turns through the runtime
- **THEN** both hosts SHALL execute through the same assembled session and turn orchestration stack

### Requirement: Tool execution context includes turn-scoped runtime state
The runtime SHALL provide tools with turn-scoped execution context that includes current messages, request interruption handles, and runtime callbacks needed for permission, notification, or mid-turn capability refresh behavior.

#### Scenario: Tool reads turn-scoped context during execution
- **WHEN** a tool executes during an active turn
- **THEN** the tool context SHALL expose the current turn history and runtime callbacks needed for that tool execution path

### Requirement: Runtime assembly registers invocation providers from package contributions and config
The runtime SHALL assemble the shared invocation registry from the built-in skill provider baseline, package-contributed invocation providers, and config-supplied providers before exposing runnable host or session surfaces.

#### Scenario: assembled runtime exposes package-owned invocation source
- **WHEN** a runtime package contributes an invocation provider and the runtime finishes assembly
- **THEN** the assembled runtime SHALL expose that provider through the same invocation-registry-backed catalog surfaces used for skills
- **AND** hosts SHALL be able to resolve visible invocations without re-registering that provider manually

### Requirement: Runtime assembly separates protocol catalog from package inventory
The runtime SHALL expose stable core protocol metadata separately from selected package inventory, package lookup metadata, and compatibility projections.

#### Scenario: assembled runtime reports both protocol and package data
- **WHEN** a caller inspects assembly metadata for a runnable runtime
- **THEN** the runtime SHALL provide stable core protocol catalog entries separately from first-party package inventory and package-lookup metadata
- **AND** SHALL allow distribution-specific package additions to vary without redefining the stable core protocol set
- **AND** SHALL keep the protocol catalog as the source of truth for stable core protocols while package-lookup and compatibility metadata remain the source of truth for package-specific canonical keys and wrapper status

### Requirement: Runtime assembly metadata SHALL publish package registration separately from package inventory
The runtime SHALL publish a `package_registration` metadata section that describes accepted and rejected external manifest registrations and their diagnostics. This section SHALL remain separate from `first_party_packages`, `first_party_package_catalog`, `package_manifests`, `package_lookup`, and `core_protocol_catalog`.

#### Scenario: caller inspects metadata after external package registration
- **WHEN** a caller inspects runtime assembly metadata after one or more external package registrations were processed
- **THEN** the metadata SHALL expose `package_registration.accepted`, `package_registration.rejected`, and `package_registration.diagnostics`
- **AND** `package_manifests` SHALL describe only the merged admitted manifest set that actually participated in assembly
- **AND** stable protocol metadata SHALL remain in `core_protocol_catalog` instead of being redefined inside `package_registration`

### Requirement: Runtime assembly metadata SHALL publish raw package candidates separately from the resolved graph
The runtime SHALL publish a `package_resolution` metadata section that reports the raw package candidate catalog, the package request inputs used for resolution, the resolved package graph, and resolution diagnostics. This section SHALL remain separate from `package_registration`, `package_manifests`, and `core_protocol_catalog`.

#### Scenario: metadata distinguishes candidate inventory from resolved package graph
- **WHEN** more than one package candidate is present for a package name or the candidate catalog contains packages that are not selected into the final runtime
- **THEN** `package_resolution.candidate_catalog` SHALL report the raw candidate inventory
- **AND** `package_resolution.resolved_graph` SHALL report only the selected candidate graph for the active runtime
- **AND** `package_manifests` SHALL continue to describe only the manifests that actually reached package assembly

### Requirement: Assembled runtime SHALL publish invocation-provider provenance without a config-owned bypass tier
The runtime SHALL publish invocation-provider provenance for the built-in baseline and package-contributed providers only.

#### Scenario: caller inspects assembled invocation-provider metadata
- **WHEN** a caller inspects invocation-provider provenance or runtime-assembly metadata from an assembled runtime
- **THEN** the runtime SHALL identify the built-in baseline provider registrations and package-contributed provider registrations
- **AND** SHALL NOT report a config-owned invocation-provider registration tier as part of the canonical assembly model

### Requirement: Assembled runtime SHALL publish package-catalog provenance and protocol-only conformance summary
The runtime SHALL publish official package-catalog provenance, resolved active package-graph provenance, and protocol-only conformance summary metadata as part of the assembled runtime view.

#### Scenario: caller inspects assembled runtime metadata
- **WHEN** a caller inspects an assembled runtime's metadata or equivalent runtime-assembly view
- **THEN** the runtime SHALL expose official package-catalog provenance, resolved active package-graph provenance, and protocol-only conformance summary metadata as distinct published artifacts
- **AND** SHALL expose per-rule conformance results within the protocol-only summary
- **AND** SHALL encode each per-rule result with the shared finding fields `rule_id`, `family`, `status`, `distribution`, `evidence`, and `canonical_path`, plus optional `compat_surface` or `replacement_path`
- **AND** SHALL NOT collapse those concerns into one ambiguous package metadata blob

### Requirement: Runtime assembly publishes closure and hardening state separately from core protocol metadata
The runtime SHALL publish closure and hardening state through a dedicated closure report at `runtime.services.metadata["closure_report"]` and `runtime.metadata["closure_report"]`, separate from the stable core protocol catalog, package inventory, and package lookup metadata.

#### Scenario: caller inspects closure report
- **WHEN** a caller inspects assembly metadata for closure or hardening information
- **THEN** the runtime SHALL publish a dedicated closure report that describes retained legacy surfaces, isolation readiness, persistence profile, and current closure status
- **AND** the runtime SHALL keep that report separate from the stable core protocol catalog entries themselves

### Requirement: Runtime assembly publishes active persistence and isolation readiness state
The runtime SHALL publish the active persistence profile and isolation readiness state for the selected assembly so embedders can distinguish lightweight and production-oriented runtime shapes.

#### Scenario: runtime-core and runtime-full report different hardening state
- **WHEN** a caller compares assembly metadata for smaller and larger supported runtime shapes
- **THEN** the runtime SHALL preserve the same stable core protocol catalog where required
- **AND** it SHALL allow closure-report fields such as persistence profile, child-run durability, transcript durability, and isolation readiness to vary by assembled runtime shape

### Requirement: Runtime assembly metadata SHALL publish WeaveRT-branded public identifiers
The runtime SHALL publish WeaveRT-branded public identifiers throughout assembly inspection surfaces that embedders consume directly. Canonical distribution names, package names, capability identifiers, protocol identifiers, and extension namespaces surfaced through runtime metadata SHALL use `weavert-*` and `weavert.*`.

#### Scenario: Caller inspects assembled runtime metadata
- **WHEN** a caller inspects runtime metadata, package catalogs, package resolution metadata, protocol catalogs, or capability lookup summaries
- **THEN** the canonical public identifiers in those inspection surfaces SHALL use `weavert-*` and `weavert.*`
- **AND** legacy `runtime-*` and `runtime.*` names SHALL NOT be advertised as the canonical assembly output

