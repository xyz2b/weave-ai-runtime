## ADDED Requirements

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
