## ADDED Requirements

### Requirement: Runtime-generated continuation inputs can request explicit turn admission
The ingress pipeline SHALL allow runtime-generated continuation inputs to override default source-based admission behavior through explicit admission metadata on runtime-generated task notifications or an equivalent runtime-owned task-notification envelope.

#### Scenario: child-run continuation input is admitted as a turn
- **WHEN** the runtime submits a child-run continuation input as a runtime-generated task notification with explicit `admission_kind=admit_turn` intent for a parent session
- **THEN** ingress SHALL normalize that input through the same ingress pipeline used for other session events
- **AND** SHALL admit it as a new turn instead of forcing transcript-only handling

#### Scenario: ordinary task notification keeps default behavior without override
- **WHEN** a task or background notification enters ingress without explicit continuation-admission intent
- **THEN** the runtime SHALL preserve the default admission behavior for that notification source
- **AND** SHALL NOT automatically upgrade all task notifications into admitted turns

### Requirement: Waiting sessions can resume through admitted runtime-generated continuation inputs
Session control SHALL be able to queue and execute admitted runtime-generated continuation inputs without requiring the host to resubmit the same event as a user prompt.

#### Scenario: waiting session resumes from child-run completion
- **WHEN** a waiting session receives an admitted runtime-generated continuation input
- **THEN** the session controller SHALL be able to transition that input through ingress and the normal turn-execution stack
- **AND** SHALL not require a separate host-originated prompt to wake the session

#### Scenario: ready session queues continuation input by default
- **WHEN** a ready session receives an admitted runtime-generated continuation input under the default continuation policy
- **THEN** the session controller SHALL queue that input for subsequent execution without eagerly starting a new turn
- **AND** SHALL only auto-resume ready sessions when an explicit runtime policy enables that behavior

#### Scenario: running session queues continuation input for later execution
- **WHEN** a runtime-generated continuation input arrives while the session already has an active turn
- **THEN** the session controller SHALL queue that input for later execution or equivalent ordered handling
- **AND** SHALL NOT start a second concurrent turn for the same session solely because the continuation input was admitted
