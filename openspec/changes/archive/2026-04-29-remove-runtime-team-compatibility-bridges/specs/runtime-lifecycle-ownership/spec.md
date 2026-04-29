## ADDED Requirements

### Requirement: Team replay and recovery SHALL remain lifecycle-participant-owned during bridge removal
The runtime SHALL keep team recovery and session-open replay behavior attached through lifecycle participants while removing package-specific team bridges from runtime-owned owner-layer APIs.

#### Scenario: session resumes with pending team state
- **WHEN** a session resumes with package-owned team replay or recovery work pending
- **THEN** the runtime SHALL execute that work through the published lifecycle-participant phases
- **AND** SHALL NOT reintroduce a controller-owned or kernel-owned team replay special case during bridge removal
