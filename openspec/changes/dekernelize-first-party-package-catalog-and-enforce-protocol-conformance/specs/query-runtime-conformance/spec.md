## ADDED Requirements

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
- **THEN** the runtime SHALL report distinct rule results for privileged service-slot, context-authority, team-bridge, provider-provenance, and kernel-assembly rule families
- **AND** SHALL encode those rule results with the shared finding fields `rule_id`, `family`, `status`, `distribution`, `evidence`, and `canonical_path`, plus optional `compat_surface` or `replacement_path`
- **AND** SHALL allow CI or embedders to determine which rule family failed without re-running ad hoc subsystem-specific audits

#### Scenario: terminal gate is green across the supported distribution matrix
- **WHEN** the runtime evaluates the terminal protocol-only gate for `runtime-core`, `runtime-default`, and `runtime-full`, including required optional-package present or absent cases
- **THEN** the gate SHALL be considered green only if every required rule family reports `pass`
- **AND** SHALL NOT treat summary publication alone as sufficient for terminal conformance
