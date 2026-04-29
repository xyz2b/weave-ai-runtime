# query-runtime-conformance Specification

## Purpose
TBD - created by archiving change add-query-runtime-protocol-golden-tests. Update Purpose after archive.
## Requirements
### Requirement: Query continuation is verified at the request payload level
The runtime SHALL be verified by request-level fixtures that assert correct `tool_use` / `tool_result` continuation structure across provider requests.

#### Scenario: Second request contains the matching tool_result block
- **WHEN** a turn executes a tool call and continues into a follow-up provider request
- **THEN** the conformance suite SHALL verify that the follow-up request contains a `tool_result` block whose `tool_use_id` matches the originating `tool_use`

### Requirement: Interrupt and resume semantics are regression-tested
The runtime SHALL be regression-tested for interrupt, partial discard, transcript resume, tool/result pairing repair behavior, and terminal metadata stability across interrupt paths.

#### Scenario: Interrupted stream resumes without invalid tool pairing
- **WHEN** a turn is interrupted mid-stream and the session is later resumed from transcript state
- **THEN** the conformance suite SHALL verify that invalid partial tool structures are discarded or repaired before the next provider request
- **AND** it SHALL verify the interrupt terminal payload contains the required stable fields without rejecting additive runtime metadata

### Requirement: Assembled orchestration paths are verified end-to-end
The runtime SHALL be regression-tested for model-generated built-in orchestration tools and host event consumption through the assembled runtime path, including structured child terminal metadata returned through tool results.

#### Scenario: Model-generated agent tool executes through assembled runtime
- **WHEN** the model emits a built-in `agent` or `skill` tool call in an assembled runtime session
- **THEN** the conformance suite SHALL verify that the tool executes through the assembled runtime wiring and that the host can consume the resulting turn events
- **AND** it SHALL verify any returned child `terminal_metadata` remains aligned with the structured child run record while tolerating additive runtime metadata

### Requirement: Context and TaskManager compatibility boundaries are regression-tested
The runtime SHALL be regression-tested to ensure that structured context carriers and shared job/task services remain authoritative while raw `runtime_context` and `TaskManager` remain compatibility-only surfaces, and SHALL publish structured conformance findings for those authority rules.

#### Scenario: primary path avoids raw runtime_context writes
- **WHEN** a conformance test exercises runtime-owned primary paths that read or update shared private state
- **THEN** the runtime SHALL preserve authoritative writes through structured private-state carriers
- **AND** SHALL NOT require raw `runtime_context` mutation as an authoritative write path

#### Scenario: primary path avoids TaskManager authority
- **WHEN** a conformance test exercises runtime-owned primary paths that perform job or task control behavior
- **THEN** the runtime SHALL preserve `JobService` and `TaskListService` as the authoritative control surfaces
- **AND** SHALL NOT require `TaskManager` materialization as part of the primary-path execution contract

#### Scenario: conformance summary reports context-authority status
- **WHEN** a caller inspects a protocol-only conformance summary or equivalent conformance metadata
- **THEN** the runtime SHALL publish structured findings for the raw-`runtime_context` and `TaskManager` authority rules
- **AND** SHALL identify the structured carriers or canonical services that satisfied those rules
- **AND** SHALL encode those findings with the shared protocol-only finding fields `rule_id`, `family`, `status`, `distribution`, `evidence`, and `canonical_path`, plus optional `compat_surface`

### Requirement: Privileged service-family protocol bindings are regression-tested without dedicated slots
The runtime SHALL be regression-tested to prove that runtime-owned primary paths consume memory, compaction, and isolation behavior through canonical protocol bindings rather than privileged dedicated service slots, and SHALL publish a structured conformance finding for that rule family.

#### Scenario: primary path resolves privileged service behavior through canonical bindings
- **WHEN** a conformance test exercises runtime-owned primary paths that require memory, compaction, or isolation behavior
- **THEN** the runtime SHALL resolve that behavior through the canonical service-family protocol bindings
- **AND** SHALL NOT require dedicated `RuntimeServices` fields to remain the source of truth for that behavior

#### Scenario: conformance inspects privileged service-family provenance
- **WHEN** a caller inspects a protocol-only conformance summary or equivalent conformance metadata
- **THEN** the runtime SHALL publish structured findings that identify the canonical binding for each migrated privileged service family
- **AND** SHALL separately identify any retained dedicated service fields as compatibility-only projections
- **AND** SHALL encode those findings with the shared protocol-only finding fields `rule_id`, `family`, `status`, `distribution`, `evidence`, and `canonical_path`, plus optional `compat_surface`

### Requirement: Team protocol-only integration is regression-tested without owner-layer bridges
The runtime SHALL be regression-tested to prove that team behavior remains available through canonical protocol surfaces without depending on package-specific owner-layer bridges, and SHALL publish structured conformance findings for the team-bridge rule family.

#### Scenario: team workflow operations resolve without bound-host wrappers
- **WHEN** a conformance test performs package-owned team workflow operations through the assembled runtime
- **THEN** the runtime SHALL resolve those operations through canonical host facets and capability lookup
- **AND** SHALL NOT require bound-host workflow helper wrappers or package-specific top-level runtime projections to remain present

#### Scenario: package-owned team events emit through generic extension events
- **WHEN** a conformance test observes package-owned team events emitted by the runtime
- **THEN** the runtime SHALL deliver those events through the generic extension-event host contract
- **AND** SHALL NOT depend on a package-specific team event method on the mandatory host bridge

#### Scenario: conformance summary reports team bridge status
- **WHEN** a caller inspects a protocol-only conformance summary or equivalent conformance metadata
- **THEN** the runtime SHALL publish structured findings for the team workflow-wrapper and host-event-bridge rules
- **AND** SHALL identify the canonical capability or host-facet path that replaced each removed bridge
- **AND** SHALL encode those findings with the shared protocol-only finding fields `rule_id`, `family`, `status`, `distribution`, `evidence`, and `canonical_path`, plus optional `compat_surface` or `replacement_path`

### Requirement: Invocation-provider provenance is regression-tested without a config-owned bypass
The runtime SHALL be regression-tested to prove that custom invocation providers enter the assembled runtime only through package contributions after the built-in baseline, and SHALL publish structured conformance findings for the provider-provenance rule family.

#### Scenario: conformance inspects provider provenance
- **WHEN** a conformance test assembles a runtime with custom invocation providers
- **THEN** the runtime SHALL report provider provenance from the built-in baseline and package-contributed registrations only
- **AND** SHALL NOT require a config-owned provider-registration bypass to make those custom providers visible

#### Scenario: conformance summary reports provider-provenance status
- **WHEN** a caller inspects a protocol-only conformance summary or equivalent conformance metadata
- **THEN** the runtime SHALL publish structured findings for the provider-provenance rule family
- **AND** SHALL identify the built-in baseline tier and package-contributed tiers that satisfied the rule
- **AND** SHALL encode those findings with the shared protocol-only finding fields `rule_id`, `family`, `status`, `distribution`, `evidence`, and `canonical_path`, plus optional `replacement_path`

### Requirement: Protocol-only conformance SHALL fail on forbidden compatibility surfaces and assembly branches
The runtime SHALL define and enforce a protocol-only conformance rule set that fails when runtime-owned primary paths depend on forbidden compatibility surfaces or forbidden package-specific kernel assembly branches.

#### Scenario: runtime-owned primary path depends on a forbidden compatibility surface
- **WHEN** a conformance test or conformance summary evaluates a runtime-owned primary path that depends on a forbidden compatibility surface
- **THEN** the runtime SHALL report that condition as a protocol-only conformance failure
- **AND** SHALL identify the forbidden compatibility surface in structured conformance metadata

#### Scenario: kernel package assembly depends on a forbidden package-specific branch
- **WHEN** a conformance test or conformance summary evaluates official package assembly and finds dependence on a forbidden kernel-owned package-specific assembly branch
- **THEN** the runtime SHALL report that condition as a protocol-only conformance failure
- **AND** SHALL identify the forbidden assembly branch or equivalent violation in structured conformance metadata

#### Scenario: conformance summary aggregates subsystem-owned rule findings
- **WHEN** a caller inspects the protocol-only conformance summary for an assembled runtime
- **THEN** the runtime SHALL report distinct rule results for privileged service-slot, context-authority, task-authority, team-bridge, provider-provenance, and kernel-assembly rule families
- **AND** SHALL encode those rule results with the shared finding fields `rule_id`, `family`, `status`, `distribution`, `evidence`, and `canonical_path`, plus optional `compat_surface` or `replacement_path`
- **AND** SHALL allow CI or embedders to determine which rule family failed without re-running ad hoc subsystem-specific audits

#### Scenario: terminal gate is green across the supported distribution matrix
- **WHEN** the runtime evaluates the terminal protocol-only gate for `runtime-core`, `runtime-default`, and `runtime-full`, including required optional-package present or absent cases
- **THEN** the gate SHALL be considered green only if every required rule family reports `pass`
- **AND** SHALL NOT treat summary publication alone as sufficient for terminal conformance

### Requirement: Runtime conformance verifies closure and hardening expectations across the supported matrix
The runtime SHALL verify compatibility retirement, persistence-profile expectations, and non-stub isolation behavior through a conformance matrix rather than leaving those closure checks to documentation only.

#### Scenario: supported runtime matrix publishes closure-family results
- **WHEN** the conformance suite evaluates the supported runtime distribution or profile matrix
- **THEN** it SHALL publish family results for compatibility retirement, persistence-profile expectations, and isolation readiness
- **AND** each family result SHALL identify the current assembly and required matrix cases through stable metadata

#### Scenario: closure-green assembly requires no stub isolation or hidden legacy default
- **WHEN** the conformance suite reports the current assembly as closure-green
- **THEN** that assembly SHALL have no successful stub isolation path for a declared stable isolation mode
- **AND** it SHALL satisfy the published default durability expectations for its active persistence profile
- **AND** it SHALL NOT depend on legacy-only compatibility surfaces as the default canonical runtime path

