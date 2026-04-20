# route-aware-tool-execution Specification

## Purpose
TBD - created by archiving change close-agent-tool-behavior-gap. Update Purpose after archive.
## Requirements
### Requirement: Agent execution resolves model routes with explicit precedence
The runtime SHALL resolve agent model routes using a stable precedence order so that child executions can reliably target different model routes in the same session.

#### Scenario: execution-time route override wins over agent default
- **WHEN** a child agent invocation includes an explicit route override and the target agent definition also declares a `model_route`
- **THEN** the runtime SHALL use the explicit route override as the resolved route
- **AND** it SHALL NOT silently fall back to the agent default route for that execution

#### Scenario: agents in the same session may resolve different routes
- **WHEN** two agent executions in the same session target different resolved model routes
- **THEN** the runtime SHALL allow each execution to use its own resolved route
- **AND** it SHALL NOT force both executions through a single shared route only because they share a session

### Requirement: Model override does not change provider ownership
The runtime SHALL treat `model` override and `model_route` resolution as separate concerns.

#### Scenario: model override stays within the resolved route
- **WHEN** a child execution specifies both a resolved route and an explicit model override
- **THEN** the runtime SHALL apply the model override only within the already resolved route
- **AND** it SHALL NOT use the model string to reroute the execution to another provider binding

### Requirement: Resolved route metadata is propagated through execution surfaces
The runtime SHALL propagate resolved route and capability metadata through the model request and child run record surfaces.

#### Scenario: model request includes resolved route metadata
- **WHEN** the runtime dispatches a model request for an agent execution with a resolved route
- **THEN** the request SHALL include the resolved route identity, provider identity, and resolved capability profile as structured fields or equivalent structured contract
- **AND** those fields SHALL NOT exist only as opaque free-form metadata

#### Scenario: child run record includes resolved route identity
- **WHEN** a child execution finishes after resolving a route
- **THEN** the corresponding child run record SHALL include both requested route hints and the final resolved route identity
- **AND** the stored terminal metadata SHALL remain attributable to that resolved route

### Requirement: Turn execution supports buffered completion for tool-capable providers
The runtime SHALL support a buffered or non-stream completion path for providers that can only expose parseable tool calls after full completion.

#### Scenario: complete-only provider returns tool-call-capable assistant output
- **WHEN** the bound model adapter cannot stream tool call deltas but can return a complete assistant response containing tool calls
- **THEN** the runtime SHALL parse those tool calls after completion
- **AND** it SHALL continue the turn through the shared tool orchestration and continuation contract

#### Scenario: complete-only provider returns a final assistant answer without tools
- **WHEN** the buffered completion path returns an assistant response with no tool calls
- **THEN** the runtime SHALL terminate the turn with the same assistant message and terminal semantics expected from the streaming path

### Requirement: Buffered and streaming execution preserve a shared terminal contract
The runtime SHALL preserve the same terminal metadata shape and ordered tool result continuation semantics across streaming and buffered execution paths.

#### Scenario: buffered path preserves terminal metadata shape
- **WHEN** a turn is executed through the buffered completion path
- **THEN** the runtime SHALL emit terminal metadata containing the same core fields as the streaming path, including stop reason, request identity, usage, and error or abort details when present
- **AND** host and test code SHALL NOT need a separate terminal metadata schema for buffered execution

#### Scenario: buffered tool results preserve ordered continuation
- **WHEN** buffered execution yields one or more tool calls that complete out of order
- **THEN** the runtime SHALL still replay tool results according to the originating tool-use order
- **AND** it SHALL preserve the same ordered continuation guarantees as the streaming tool path

