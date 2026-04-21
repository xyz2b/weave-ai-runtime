# query-runtime-conformance Specification

## Purpose
TBD - created by archiving change add-query-runtime-protocol-golden-tests. Update Purpose after archive.
## Requirements
### Requirement: Query continuation is verified at the request payload level
The runtime SHALL be verified by request-level fixtures that assert correct `tool_use` / `tool_result` continuation structure across provider requests.

#### Scenario: Second request contains the matching tool_result block
- **WHEN** a turn executes a tool call and continues into a follow-up provider request
- **THEN** the conformance suite SHALL verify that the follow-up request contains a `tool_result` block whose `tool_use_id` matches the originating `tool_use`

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

