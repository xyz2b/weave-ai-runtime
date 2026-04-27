## ADDED Requirements

### Requirement: Invocation-provider registration after the built-in baseline SHALL be package-only
The runtime SHALL register the built-in skill invocation-provider baseline first and SHALL register any additional custom invocation providers only through package-contributed invocation-provider registrations.

#### Scenario: runtime assembles custom providers
- **WHEN** the runtime assembles one or more custom invocation providers beyond the built-in baseline
- **THEN** it SHALL register those providers through package-contributed invocation-provider registrations
- **AND** SHALL NOT admit an additional config-owned invocation-provider registration tier after the built-in baseline
