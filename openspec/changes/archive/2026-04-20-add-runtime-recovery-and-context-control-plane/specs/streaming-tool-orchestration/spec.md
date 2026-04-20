## MODIFIED Requirements

### Requirement: Tool results replay in original tool_use order
The runtime SHALL commit `tool_result` blocks back into continuation history in the same order as the originating `tool_use` blocks, even if the underlying tool executions finish in a different order and even if the replay payload for a given slot is a full result, a summarized result, or a stable artifact reference produced from a configured budget-hook decision.

#### Scenario: Concurrent tools complete out of order
- **WHEN** two or more concurrently executed tools finish in a different order from the order of their originating `tool_use` blocks
- **THEN** the runtime SHALL replay the resulting `tool_result` blocks in the original `tool_use` order seen by the model

#### Scenario: Budget hook downgrade still occupies the original replay slot
- **WHEN** a configured budget hook marks a tool result for summarization or externalization
- **THEN** the runtime SHALL replay the summarized or referenced `tool_result` in the original `tool_use` slot rather than skipping that slot or moving the replay order

## ADDED Requirements

### Requirement: Tool-result spillover remains replay-compatible
The runtime SHALL preserve replay compatibility when large tool results are externalized, by carrying stable spillover metadata that links the replayed `tool_result` block to the full stored payload.

#### Scenario: Externalized tool result exposes stable reference metadata
- **WHEN** the runtime externalizes a large tool result during context preparation
- **THEN** the replayed `tool_result` metadata SHALL include a stable reference or equivalent artifact identifier that can be associated with the full stored payload together with the decision reason or policy tag that produced the downgrade

### Requirement: Spillover replay remains defined when artifact payloads are unavailable
The runtime SHALL keep replay order and slot semantics defined even when a spillover artifact cannot be resolved at replay or resume time.

#### Scenario: Missing spillover artifact preserves replay slot
- **WHEN** replay needs a spillover artifact reference whose payload is unavailable
- **THEN** the runtime SHALL preserve the original `tool_result` slot through a degraded placeholder or summarized fallback plus diagnostics rather than dropping or reordering the replay entry
