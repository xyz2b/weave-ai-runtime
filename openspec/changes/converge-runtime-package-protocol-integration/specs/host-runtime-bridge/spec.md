## ADDED Requirements

### Requirement: Optional package-specific host operations SHALL be surfaced through host facets or capability-detected extensions
The runtime SHALL surface optional package-specific host operations through package-owned host facets or equivalent capability-detected extension contracts instead of widening the mandatory host bridge for each official package feature.

#### Scenario: Official package exposes host-visible optional operations
- **WHEN** an official package contributes host-visible operations that are not required by every host
- **THEN** the runtime SHALL make those operations available through a package-owned host-facet or equivalent extension surface
- **AND** hosts that do not opt into that package SHALL still remain conformant without implementing those optional operations

### Requirement: Host facet availability SHALL be discoverable through one runtime-owned path
The runtime SHALL provide one runtime-owned discovery path that allows hosts or callers to determine which optional package-owned host facets are available in the active runtime.

#### Scenario: Caller checks for optional package-owned host operations
- **WHEN** a caller or bound host needs to determine whether an optional package-owned host facet is available
- **THEN** the runtime SHALL expose that availability through one shared discovery path
- **AND** it SHALL NOT require the caller to infer facet availability from package-specific host method presence or ad hoc object inspection

### Requirement: Missing host facets SHALL fail through a structured runtime outcome
The runtime SHALL surface absent or unavailable optional package-owned host facets through a structured runtime outcome rather than through package-specific missing-method behavior.

#### Scenario: Caller invokes an unavailable optional host facet
- **WHEN** a caller attempts to use an optional host facet that is not available in the active runtime
- **THEN** the runtime SHALL return a structured not-available or unsupported outcome through the shared host-extension path
- **AND** it SHALL NOT require package-specific exception patterns or missing-method checks as the normative behavior

### Requirement: Mandatory host bridge SHALL remain focused on shared runtime concerns
The runtime SHALL keep the mandatory host bridge focused on lifecycle, permission, elicitation, notifications, turn events, and other shared runtime concerns even when official packages add optional host-visible features.

#### Scenario: Runtime adds a new official package with optional host helpers
- **WHEN** an official package adds host-visible helpers that are specific to that package
- **THEN** the runtime SHALL keep the mandatory host bridge limited to shared runtime concerns
- **AND** it SHALL avoid promoting those package-specific helpers into the mandatory host bridge unless they become framework-wide required behavior
