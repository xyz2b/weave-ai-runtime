## MODIFIED Requirements

### Requirement: Interrupt and resume semantics are regression-tested
The runtime SHALL be regression-tested for interrupt, partial discard, transcript resume, tool/result pairing repair behavior, and terminal metadata stability across interrupt paths.

#### Scenario: Interrupted stream resumes without invalid tool pairing
- **WHEN** a turn is interrupted mid-stream and the session is later resumed from transcript state
- **THEN** the conformance suite SHALL verify that invalid partial tool structures are discarded or repaired before the next provider request
- **AND** it SHALL verify the interrupt terminal payload contains the required stable fields without rejecting additive runtime metadata

### Requirement: Assembled orchestration paths are verified end-to-end
The runtime SHALL be regression-tested for model-generated built-in orchestration tools and host event consumption through the assembled runtime path, including structured child terminal metadata returned through tool results.

#### Scenario: Model-generated agent tool executes through assembled runtime
- **WHEN** the model emits a built-in `agent` or `skill` tool call in an assembled runtime session
- **THEN** the conformance suite SHALL verify that the tool executes through the assembled runtime wiring and that the host can consume the resulting turn events
- **AND** it SHALL verify any returned child `terminal_metadata` remains aligned with the structured child run record while tolerating additive runtime metadata
