# runtime-persistence-profiles Specification

## Purpose
TBD - created by archiving change complete-runtime-microkernel-closure-and-hardening. Update Purpose after archive.
## Requirements
### Requirement: Runtime publishes a named persistence profile with per-surface durability semantics
The runtime SHALL publish a named persistence profile under `runtime.services.metadata["closure_report"]["persistence_profile"]` and `runtime.metadata["closure_report"]["persistence_profile"]` that declares the durability expectations for transcript history, child-run history, jobs, task lists, team state, and memory for the active assembly.

#### Scenario: caller inspects persistence profile metadata
- **WHEN** a caller inspects runtime assembly metadata for persistence information
- **THEN** the runtime SHALL publish the active persistence profile name and the durability state of each supported persistence surface
- **AND** the runtime SHALL distinguish durable, non-durable, and host-provided surfaces explicitly

### Requirement: Production-oriented profiles bundle durable transcript and child-run history
The runtime SHALL provide at least one first-party production-oriented persistence profile in which transcript history and child-run history are both durable through bundled runtime-owned package wiring.

#### Scenario: production profile binds durable transcript and child-run stores
- **WHEN** a production-oriented runtime profile is assembled through the supported first-party package set
- **THEN** the runtime SHALL bind a durable transcript path and a durable child-run path by default
- **AND** the runtime SHALL preserve transcript and child-run history across process restart or equivalent runtime reassembly

#### Scenario: lightweight profile can remain non-durable with explicit metadata
- **WHEN** a lightweight runtime profile is assembled without bundled durable transcript or child-run persistence
- **THEN** the runtime MAY keep those histories non-durable by default
- **AND** the runtime SHALL publish that weaker durability contract explicitly in the active persistence profile metadata

