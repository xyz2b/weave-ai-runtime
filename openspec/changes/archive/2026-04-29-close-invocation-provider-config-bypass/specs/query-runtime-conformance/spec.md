## ADDED Requirements

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
