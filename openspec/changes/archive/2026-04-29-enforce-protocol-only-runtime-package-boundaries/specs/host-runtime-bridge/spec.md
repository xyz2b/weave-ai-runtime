## ADDED Requirements

### Requirement: Canonical package-owned host helpers SHALL be discovered through host facets
The runtime SHALL treat host-facet discovery as the canonical path for package-owned host-visible helpers even when compatibility wrapper methods remain temporarily available on runtime-owned surfaces.

#### Scenario: caller accesses an optional package-owned host helper
- **WHEN** a caller or bound host needs an optional package-owned host-visible helper
- **THEN** the runtime SHALL make that helper available through the shared host-facet discovery path
- **AND** any retained package-specific wrapper method SHALL remain a compatibility projection over the same host-facet-owned behavior

### Requirement: Mandatory host bridge SHALL NOT grow new package-specific methods for first-party package behavior
The runtime SHALL keep the mandatory host bridge limited to shared runtime concerns and SHALL NOT add new package-specific mandatory host methods solely because one official package emits structured events or host-visible helper behavior.

#### Scenario: package requires structured host interaction beyond shared runtime concerns
- **WHEN** an official package introduces structured host interaction that is specific to that package
- **THEN** the runtime SHALL expose that interaction through a package-owned extension path or bounded compatibility surface
- **AND** it SHALL NOT widen the mandatory host bridge with a new package-specific required method unless that behavior becomes a shared runtime concern
