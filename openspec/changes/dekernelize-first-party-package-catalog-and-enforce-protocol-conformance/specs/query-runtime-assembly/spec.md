## ADDED Requirements

### Requirement: Assembled runtime SHALL publish package-catalog provenance and protocol-only conformance summary
The runtime SHALL publish official package-catalog provenance, resolved active package-graph provenance, and protocol-only conformance summary metadata as part of the assembled runtime view.

#### Scenario: caller inspects assembled runtime metadata
- **WHEN** a caller inspects an assembled runtime's metadata or equivalent runtime-assembly view
- **THEN** the runtime SHALL expose official package-catalog provenance, resolved active package-graph provenance, and protocol-only conformance summary metadata as distinct published artifacts
- **AND** SHALL expose per-rule conformance results within the protocol-only summary
- **AND** SHALL encode each per-rule result with the shared finding fields `rule_id`, `family`, `status`, `distribution`, `evidence`, and `canonical_path`, plus optional `compat_surface` or `replacement_path`
- **AND** SHALL NOT collapse those concerns into one ambiguous package metadata blob
