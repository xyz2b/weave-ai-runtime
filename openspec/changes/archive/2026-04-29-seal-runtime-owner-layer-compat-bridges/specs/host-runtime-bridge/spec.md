## ADDED Requirements

### Requirement: Optional package-owned host operations SHALL resolve through host facets
The runtime SHALL expose optional package-owned host operations through host-facet discovery or an equivalently bounded extension path, rather than widening the mandatory `HostRuntime` bridge contract for every host.

#### Scenario: host uses an optional package-owned workflow helper
- **WHEN** a bound host needs an optional first-party package operation such as team workflow observation or response
- **THEN** the runtime SHALL resolve that operation through the canonical host facet or the corresponding runtime-owned bounded adapter
- **AND** SHALL keep the mandatory `HostRuntime` bridge valid for hosts that do not use that optional helper

### Requirement: Retained host workflow helpers SHALL remain additive compatibility wrappers
The runtime SHALL treat retained host-facing workflow helpers on `BoundHostRuntime` as additive compatibility wrappers over canonical workflow resolution and validation, not as mandatory bridge growth.

#### Scenario: compatibility helper delegates to canonical workflow path
- **WHEN** a caller invokes `BoundHostRuntime.list_team_workflows()` or `BoundHostRuntime.respond_team_workflow()`
- **THEN** the runtime SHALL scope and validate that request through the same canonical workflow service or host-facet-backed path used by the runtime-owned implementation
- **AND** SHALL NOT require the bound host to implement additional package-specific mandatory protocol methods

#### Scenario: optional workflow helper is unavailable
- **WHEN** the active runtime distribution does not provide the relevant package-owned workflow capability or host facet
- **THEN** observation helpers such as `list_team_workflows()` SHALL degrade to an empty result, while mutating helpers such as `respond_team_workflow()` SHALL fail with an explicit not-available error or equivalent bounded availability failure
- **AND** SHALL NOT widen the mandatory host bridge to compensate for that missing package behavior
