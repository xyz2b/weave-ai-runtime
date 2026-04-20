# query-message-protocol Specification

## Purpose
TBD - created by archiving change align-query-message-protocol. Update Purpose after archive.
## Requirements
### Requirement: API-bound conversation history preserves structured content blocks
The runtime SHALL represent API-bound turn history as structured content blocks rather than flattened strings. At minimum, the protocol SHALL preserve `text`, `tool_use`, and `tool_result` block semantics with stable identifiers across continuation boundaries.

#### Scenario: Assistant tool use survives continuation
- **WHEN** a model response emits a tool call during a turn
- **THEN** the runtime SHALL append an assistant message containing a `tool_use` block with a stable call identifier and normalized tool input

### Requirement: Tool execution results are re-fed as user tool_result blocks
The runtime SHALL encode tool execution output for continuation as user messages containing `tool_result` blocks that reference the originating `tool_use` identifier.

#### Scenario: Tool result keeps the original tool_use reference
- **WHEN** a tool call completes during a turn
- **THEN** the runtime SHALL construct a user message containing a `tool_result` block whose `tool_use_id` matches the originating assistant `tool_use` block

### Requirement: Message history is normalized and repaired before provider invocation
The runtime SHALL normalize API-bound message history before each provider request, including merging adjacent compatible messages, normalizing tool payloads, and repairing broken `tool_use` / `tool_result` pairing.

#### Scenario: Broken tool/result pairing is repaired before the next request
- **WHEN** the pending message history contains an assistant `tool_use` without a matching user `tool_result`, or an orphaned `tool_result` without a matching `tool_use`
- **THEN** the runtime SHALL repair or remove the invalid structure before sending the next provider request

### Requirement: Transcript persistence preserves structured message content
The runtime SHALL persist and restore structured message content without flattening API-bound blocks into opaque strings.

#### Scenario: Transcript round-trip preserves block structure
- **WHEN** a session transcript containing `tool_use` and `tool_result` blocks is written and then reloaded
- **THEN** the restored transcript SHALL preserve the original block types and stable identifiers needed for continuation

### Requirement: Legacy flat transcripts are read compatibly
The runtime SHALL provide best-effort compatibility for pre-migration flat transcripts by preserving text content without inventing synthetic tool/result structure.

#### Scenario: Legacy flat transcript is loaded after protocol migration
- **WHEN** the runtime loads an older transcript entry that stores only plain string content
- **THEN** the runtime SHALL preserve that text content as a text block and SHALL NOT fabricate `tool_use` or `tool_result` identifiers that were never persisted

