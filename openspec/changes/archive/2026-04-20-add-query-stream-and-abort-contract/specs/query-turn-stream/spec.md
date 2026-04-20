## ADDED Requirements

### Requirement: Turn engine exposes a host-consumable turn event stream
The runtime SHALL expose a turn-scoped async event stream that reports request lifecycle events, block-level streaming progress, finalized conversation messages, and terminal turn metadata.

#### Scenario: Host observes request lifecycle and block deltas
- **WHEN** a host starts a new turn against the runtime
- **THEN** the runtime SHALL emit a request-start event followed by block-level stream events and finalized messages through a single turn event stream

### Requirement: Model requests are abort-capable
The runtime SHALL allow an in-flight model request to be interrupted through an explicit request-scoped abort signal.

#### Scenario: User interrupt aborts a slow model stream
- **WHEN** a turn is streaming from the model and the session is interrupted
- **THEN** the runtime SHALL propagate the interrupt through the request signal and terminate the in-flight model stream without waiting for normal completion

### Requirement: Terminal turn metadata is surfaced explicitly
The runtime SHALL surface terminal metadata for each provider attempt and completed turn, including stop reason and provider usage details when available.

#### Scenario: Turn completes with terminal metadata
- **WHEN** a provider response reaches message stop or an explicit terminal error state
- **THEN** the runtime SHALL expose stop reason and available usage/request metadata through the turn result contract

### Requirement: Incomplete streamed blocks are not committed to continuation history
The runtime SHALL discard or explicitly mark incomplete streamed content so that partial blocks do not become part of the next provider request.

#### Scenario: Interrupted partial tool input is discarded
- **WHEN** a turn is interrupted while a `tool_use` block or text block is still incomplete
- **THEN** the runtime SHALL prevent the incomplete block from being committed into continuation history for the next turn iteration
