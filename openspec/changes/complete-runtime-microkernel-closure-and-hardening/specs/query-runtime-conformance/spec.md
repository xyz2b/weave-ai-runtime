## ADDED Requirements

### Requirement: Runtime conformance verifies closure and hardening expectations across the supported matrix
The runtime SHALL verify compatibility retirement, persistence-profile expectations, and non-stub isolation behavior through a conformance matrix rather than leaving those closure checks to documentation only.

#### Scenario: supported runtime matrix publishes closure-family results
- **WHEN** the conformance suite evaluates the supported runtime distribution or profile matrix
- **THEN** it SHALL publish family results for compatibility retirement, persistence-profile expectations, and isolation readiness
- **AND** each family result SHALL identify the current assembly and required matrix cases through stable metadata

#### Scenario: closure-green assembly requires no stub isolation or hidden legacy default
- **WHEN** the conformance suite reports the current assembly as closure-green
- **THEN** that assembly SHALL have no successful stub isolation path for a declared stable isolation mode
- **AND** it SHALL satisfy the published default durability expectations for its active persistence profile
- **AND** it SHALL NOT depend on legacy-only compatibility surfaces as the default canonical runtime path
