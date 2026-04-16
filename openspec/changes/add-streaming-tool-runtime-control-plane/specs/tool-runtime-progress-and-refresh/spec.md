## ADDED Requirements

### Requirement: Tool progress is surfaced through the turn event stream
The runtime SHALL surface in-flight tool progress updates through the turn event stream and bound host bridge without requiring hosts to poll tool-local state.

#### Scenario: 长运行工具持续上报进度
- **WHEN** a long-running tool emits one or more progress updates during execution
- **THEN** runtime SHALL publish those updates as turn-scoped host-consumable events before the tool has completed

### Requirement: Capability refresh updates subsequent tool visibility
The runtime SHALL treat a tool-requested capability refresh as a control-plane update that affects subsequent tool resolution and subsequent model requests after the refresh is accepted.

#### Scenario: 工具刷新后下一轮请求看到新的 tools
- **WHEN** a tool triggers a capability refresh that changes the effective available tool pool
- **THEN** runtime SHALL use the refreshed tool visibility for subsequent tool resolution and for the next provider request in that continuation
