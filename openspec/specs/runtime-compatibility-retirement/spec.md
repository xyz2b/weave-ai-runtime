# runtime-compatibility-retirement Specification

## Purpose
TBD - created by archiving change complete-runtime-microkernel-closure-and-hardening. Update Purpose after archive.
## Requirements
### Requirement: Runtime publishes a finite compatibility-retirement inventory
The runtime SHALL publish a finite machine-readable compatibility-retirement inventory under `runtime.services.metadata["closure_report"]["compatibility_retirement"]` and `runtime.metadata["closure_report"]["compatibility_retirement"]`, including remaining legacy compatibility surfaces, their migration targets, and whether each surface is enabled by default, legacy-mode only, or fully retired.

#### Scenario: caller inspects compatibility retirement state
- **WHEN** a caller inspects runtime assembly metadata for compatibility-retirement information
- **THEN** the runtime SHALL expose each retained legacy surface with its canonical replacement path and activation status
- **AND** the runtime SHALL distinguish default primary-path surfaces from legacy-mode-only surfaces

### Requirement: Default runtime paths do not silently re-promote retired legacy surfaces
The runtime SHALL ensure that a retired or legacy-only surface cannot become the default canonical lookup path for new runtime-owned integration.

#### Scenario: default runtime denies canonical legacy lookup
- **WHEN** a caller or runtime-owned path attempts to use a legacy-only surface as the canonical integration path without explicit legacy enablement
- **THEN** the runtime SHALL return a structured absence, rejection, or deactivated outcome
- **AND** the runtime SHALL expose the canonical migration target for that surface

#### Scenario: explicit legacy mode is observable
- **WHEN** an embedder explicitly enables legacy compatibility behavior for a retired surface family
- **THEN** the runtime SHALL mark that family as legacy-enabled in the published compatibility-retirement inventory
- **AND** the runtime SHALL NOT report the current assembly as closure-green for that family

### Requirement: Authoritative legacy coordination writes are blocked outside legacy mode
The runtime SHALL reject new authoritative coordination or state ownership that depends solely on shared legacy `runtime_context` or `TaskManager` compatibility paths outside explicit legacy mode.

#### Scenario: runtime-owned path attempts authoritative legacy write
- **WHEN** a runtime-owned integration attempts to treat shared legacy `runtime_context` or `TaskManager` state as the only authoritative coordination path
- **THEN** the runtime SHALL surface a structured regression diagnostic or equivalent blocking result
- **AND** the runtime SHALL require a canonical control-plane or private-context path instead

