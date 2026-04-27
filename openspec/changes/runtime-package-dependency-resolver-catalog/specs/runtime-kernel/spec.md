## ADDED Requirements

### Requirement: Kernel package assembly SHALL resolve a manifest graph before contribution assembly
The runtime kernel SHALL build a local package candidate catalog from official first-party manifests and admitted external registrations, apply distribution defaults and explicit package requests to that catalog, and resolve a concrete manifest graph before dependency ordering and package contribution assembly begin.

#### Scenario: kernel resolves a graph that includes an external candidate
- **WHEN** the selected runtime includes official first-party packages and the admitted external registration set adds another package candidate
- **THEN** the kernel SHALL resolve the combined candidate graph before package contribution assembly
- **AND** SHALL hand only the selected manifest graph to the downstream dependency-ordering path

### Requirement: Resolution failures SHALL block package contribution assembly deterministically
The runtime kernel SHALL surface package-resolution diagnostics before package contribution assembly and SHALL NOT proceed into services or runtime package assembly when the requested package graph cannot be resolved.

#### Scenario: conflicting package constraints block assembly
- **WHEN** package resolution fails because the candidate catalog cannot satisfy all requested package constraints
- **THEN** the kernel SHALL emit structured resolution diagnostics for that runtime instance
- **AND** SHALL stop before invoking package contribution assembly for an unresolved graph
