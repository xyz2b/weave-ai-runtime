## MODIFIED Requirements

### Requirement: Hooks return structured effects that can influence runtime flow
The runtime SHALL allow hooks to return structured effects that can add context, update tool input, request same-turn continuation, request session blocking, provide request overrides, emit notifications, or satisfy elicitation requests.

#### Scenario: Pre-tool hook updates input
- **WHEN** a `PreToolUse` hook returns an effect containing updated tool input
- **THEN** the runtime SHALL use the updated input for the tool call instead of the original input

#### Scenario: Stop hook requests same-turn continuation
- **WHEN** a `Stop` hook returns a structured effect requesting continuation together with injected messages or a request override
- **THEN** the runtime SHALL surface that result as a structured stop outcome for recovery handling instead of finalizing the turn immediately

#### Scenario: Stop hook blocks session completion
- **WHEN** a `Stop` hook returns a structured effect requesting session blocking rather than normal completion
- **THEN** the runtime SHALL not finalize the turn as completed and SHALL preserve the blocked outcome according to the runtime flow contract

### Requirement: Hook effect aggregation is deterministic
The runtime SHALL aggregate multiple hook effects through a deterministic order and conflict-resolution contract rather than leaving multi-hook outcomes to incidental implementation order.

#### Scenario: Ordered context and notification aggregation is stable
- **WHEN** multiple matching hooks emit additional context fragments or notifications in one phase
- **THEN** the runtime SHALL aggregate those fragments in stable registration order so repeated runs produce the same ordered hook output

#### Scenario: Stop disposition conflicts follow explicit precedence
- **WHEN** multiple matching stop hooks request different structured dispositions in the same turn
- **THEN** the runtime SHALL resolve those conflicts through an explicit precedence contract for stop outcomes rather than by whichever hook happened to run last
