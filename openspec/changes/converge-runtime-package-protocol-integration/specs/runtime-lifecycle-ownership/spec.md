## ADDED Requirements

### Requirement: Package lifecycle participants SHALL preserve core lifecycle ownership
The runtime SHALL allow package-contributed lifecycle participants to run during runtime start, runtime recovery, session open, and session close without transferring host-, session-, or turn-scope ownership away from the core lifecycle managers.

#### Scenario: Session-close participant runs without owning session close
- **WHEN** an official package contributes session-close behavior through a lifecycle participant
- **THEN** the runtime SHALL invoke that participant within the runtime-owned session-close phase
- **AND** the `SessionController` SHALL remain the owner of session-close ordering, cleanup, and terminal state transitions

#### Scenario: Runtime-recovery participant runs without owning runtime startup
- **WHEN** an official package contributes runtime-recovery behavior through a lifecycle participant
- **THEN** the runtime SHALL invoke that participant within runtime-owned startup or recovery sequencing
- **AND** the bound host runtime, kernel assembly, and turn stack ownership model SHALL remain unchanged

### Requirement: Package lifecycle participants SHALL run in owner-defined deterministic order
The runtime SHALL invoke package-contributed lifecycle participants in a deterministic order defined by the runtime-owned lifecycle manager for the active phase.

#### Scenario: Multiple participants attach to the same lifecycle phase
- **WHEN** more than one official package contributes participants for the same runtime-owned lifecycle phase
- **THEN** the runtime SHALL invoke those participants in one deterministic owner-defined order
- **AND** that ordering SHALL remain under the control of the runtime-owned lifecycle manager rather than individual packages

### Requirement: Participant failure SHALL NOT bypass remaining owner-managed lifecycle work
The runtime SHALL treat package lifecycle participant failure as a lifecycle-phase failure signal or diagnostic without skipping the remaining owner-managed cleanup or sequencing obligations for that phase.

#### Scenario: Session-close participant fails during cleanup
- **WHEN** a package lifecycle participant fails during a runtime-owned session-close phase
- **THEN** the runtime SHALL continue the remaining owner-managed session-close sequencing on a best-effort basis
- **AND** it SHALL surface the participant failure through diagnostics, terminal metadata, or equivalent structured runtime reporting

#### Scenario: Runtime-recovery participant fails during startup recovery
- **WHEN** a package lifecycle participant fails during runtime-owned startup or recovery sequencing
- **THEN** the runtime SHALL report that participant failure through the runtime-owned recovery path
- **AND** it SHALL preserve runtime-owned control of the remaining startup or recovery sequencing outcome
