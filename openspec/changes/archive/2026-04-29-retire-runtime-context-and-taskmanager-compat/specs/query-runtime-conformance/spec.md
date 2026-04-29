## ADDED Requirements

### Requirement: Context and TaskManager compatibility boundaries are regression-tested
The runtime SHALL be regression-tested to ensure that structured context carriers and shared job/task services remain authoritative while raw `runtime_context` and `TaskManager` remain compatibility-only surfaces, and SHALL publish structured conformance findings for those authority rules.

#### Scenario: primary path avoids raw runtime_context writes
- **WHEN** a conformance test exercises runtime-owned primary paths that read or update shared private state
- **THEN** the runtime SHALL preserve authoritative writes through structured private-state carriers
- **AND** SHALL NOT require raw `runtime_context` mutation as an authoritative write path

#### Scenario: primary path avoids TaskManager authority
- **WHEN** a conformance test exercises runtime-owned primary paths that perform job or task control behavior
- **THEN** the runtime SHALL preserve `JobService` and `TaskListService` as the authoritative control surfaces
- **AND** SHALL NOT require `TaskManager` materialization as part of the primary-path execution contract

#### Scenario: conformance summary reports context-authority status
- **WHEN** a caller inspects a protocol-only conformance summary or equivalent conformance metadata
- **THEN** the runtime SHALL publish structured findings for the raw-`runtime_context` and `TaskManager` authority rules
- **AND** SHALL identify the structured carriers or canonical services that satisfied those rules
- **AND** SHALL encode those findings with the shared protocol-only finding fields `rule_id`, `family`, `status`, `distribution`, `evidence`, and `canonical_path`, plus optional `compat_surface`
