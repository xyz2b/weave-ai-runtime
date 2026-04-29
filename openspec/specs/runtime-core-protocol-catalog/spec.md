# runtime-core-protocol-catalog Specification

## Purpose
TBD - created by archiving change stabilize-runtime-core-protocol-symmetry. Update Purpose after archive.
## Requirements
### Requirement: Runtime SHALL publish a stable core protocol catalog
The runtime SHALL publish a stable catalog of its core microkernel protocols, including their canonical names, owners, binding boundaries, discovery surfaces, and compatibility status.

#### Scenario: assembled runtime exposes protocol catalog
- **WHEN** a caller inspects an assembled runtime's metadata or equivalent published protocol inventory
- **THEN** the runtime SHALL identify the stable core protocols it supports, including transcript persistence, job control, task-list control, permission, elicitation, context contribution, invocation-provider registration, and host binding
- **AND** SHALL describe the canonical binding or discovery surface for each protocol

### Requirement: Core protocol catalog schema and minimum fields SHALL be versioned and stable
The runtime SHALL publish the stable core protocol catalog through a versioned machine-readable schema whose minimum required fields include protocol id, owner, binding boundary, discovery surface, and compatibility status.

#### Scenario: conformance test inspects protocol catalog entry
- **WHEN** a conformance test or host inspects one entry in the stable core protocol catalog
- **THEN** the runtime SHALL expose the catalog schema version together with the minimum required fields for that protocol entry
- **AND** SHALL NOT require the caller to infer stable protocol identity from package inventory or compatibility metadata alone

### Requirement: Stable core protocols SHALL remain distinct from package capabilities
The runtime SHALL distinguish stable core protocol entries from optional package capabilities, host facets, lifecycle participants, and compatibility wrappers.

#### Scenario: caller inspects package inventory and protocol catalog
- **WHEN** a caller inspects both the stable protocol catalog and the selected runtime package inventory
- **THEN** the runtime SHALL report package-contributed capabilities separately from the stable core protocol entries
- **AND** SHALL NOT imply that every package capability is itself part of the stable microkernel protocol set

### Requirement: Stable core protocol identity SHALL hold across distributions
The runtime SHALL keep the identity of the stable core protocol catalog consistent across supported first-party distributions, even when those distributions select different optional packages.

#### Scenario: runtime-core and runtime-full expose the same core protocol identities
- **WHEN** two supported runtime distributions are assembled with different first-party package selections
- **THEN** the runtime SHALL preserve the same stable core protocol names and canonical binding guidance across both distributions
- **AND** SHALL express distribution-specific additions separately as package inventory or optional capability metadata

