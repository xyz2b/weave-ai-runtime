## ADDED Requirements

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
