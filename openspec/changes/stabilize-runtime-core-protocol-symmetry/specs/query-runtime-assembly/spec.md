## ADDED Requirements

### Requirement: Runtime assembly separates protocol catalog from package inventory
The runtime SHALL expose stable core protocol metadata separately from selected package inventory, package lookup metadata, and compatibility projections.

#### Scenario: assembled runtime reports both protocol and package data
- **WHEN** a caller inspects assembly metadata for a runnable runtime
- **THEN** the runtime SHALL provide stable core protocol catalog entries separately from first-party package inventory and package-lookup metadata
- **AND** SHALL allow distribution-specific package additions to vary without redefining the stable core protocol set
- **AND** SHALL keep the protocol catalog as the source of truth for stable core protocols while package-lookup and compatibility metadata remain the source of truth for package-specific canonical keys and wrapper status
