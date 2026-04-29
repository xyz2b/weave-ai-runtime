## ADDED Requirements

### Requirement: Assembled runtime SHALL publish invocation-provider provenance without a config-owned bypass tier
The runtime SHALL publish invocation-provider provenance for the built-in baseline and package-contributed providers only.

#### Scenario: caller inspects assembled invocation-provider metadata
- **WHEN** a caller inspects invocation-provider provenance or runtime-assembly metadata from an assembled runtime
- **THEN** the runtime SHALL identify the built-in baseline provider registrations and package-contributed provider registrations
- **AND** SHALL NOT report a config-owned invocation-provider registration tier as part of the canonical assembly model
