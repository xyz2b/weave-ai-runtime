# streaming-tool-orchestration Specification

## Purpose
TBD - created by archiving change add-streaming-tool-runtime-control-plane. Update Purpose after archive.
## Requirements
### Requirement: Tool executor selection is based on normalized model capabilities
The runtime SHALL select its tool execution mode from normalized model capabilities exposed by the bound model adapter rather than from provider-specific names or hard-coded provider branches.

#### Scenario: 不同 provider 共享同一套 executor 选择逻辑
- **WHEN** two different model providers expose the same normalized tool-calling capability profile through their adapters
- **THEN** runtime SHALL select the same tool executor tier for both providers

### Requirement: Tool execution supports tiered automatic downgrade
The runtime SHALL support at least three tool execution tiers named `FullStreamingToolExecutor`, `BufferedToolExecutor`, and `BatchToolExecutor`, and SHALL automatically choose the highest viable tier for the current model capability profile.

#### Scenario: provider 缺少 streamed finalize boundary
- **WHEN** the bound model adapter exposes structured tool calls but cannot guarantee a safe tool-call finalize boundary before `message_stop`
- **THEN** runtime SHALL downgrade from `FullStreamingToolExecutor` to `BufferedToolExecutor`

#### Scenario: provider 只能在完整响应后给出可解析 tool call
- **WHEN** the bound model adapter cannot expose structured streaming tool calls but can provide parseable tool calls after full response completion
- **THEN** runtime SHALL downgrade to `BatchToolExecutor`

### Requirement: Tool execution fails closed when no viable executor tier exists
The runtime SHALL avoid starting tool execution when the bound model adapter cannot provide parseable tool calls for any supported executor tier.

#### Scenario: provider 完全不支持可解析 tool call
- **WHEN** the bound model adapter cannot expose streamed tool calls, buffered structured tool calls, or parseable tool calls after full response completion
- **THEN** runtime SHALL not select a tool executor tier for that turn and SHALL treat the provider as tool-ineligible for that request

### Requirement: Tool execution can start from streamed tool_use blocks
The runtime SHALL allow eligible tool calls to begin execution as soon as a streamed `tool_use` block has been finalized, without waiting for the enclosing assistant message to reach message stop.

#### Scenario: streamed tool_use 在 message_stop 之前完成
- **WHEN** provider stream emits a complete `tool_use` block before the assistant message has fully stopped
- **THEN** runtime SHALL be able to start that tool call immediately while continuing to track the remaining assistant response

#### Scenario: full streaming tier 支持 early start
- **WHEN** runtime selects `FullStreamingToolExecutor` for the current turn
- **THEN** runtime SHALL allow eligible tool calls to start before `message_stop` as soon as their tool-call finalize boundary is reached

### Requirement: Lower tool execution tiers preserve shared orchestration semantics
The runtime SHALL preserve explicit tool status mapping, ordered replay, and failure-policy semantics across `FullStreamingToolExecutor`, `BufferedToolExecutor`, and `BatchToolExecutor`, even when early-start behavior is unavailable in lower tiers.

#### Scenario: buffered tier 不支持 early start 但保留结果顺序语义
- **WHEN** runtime selects `BufferedToolExecutor` because the provider lacks a safe early-start boundary
- **THEN** runtime SHALL delay tool start until the buffered boundary is reached while preserving ordered replay and explicit tool outcome status

### Requirement: All executor tiers preserve the same lifecycle object model
The runtime SHALL preserve the `ToolCallEnvelope -> ResolvedToolCall -> ToolOutcome` lifecycle model across `FullStreamingToolExecutor`, `BufferedToolExecutor`, and `BatchToolExecutor`, even when the observation boundary that creates the initial envelope differs by tier.

#### Scenario: batch tier 仍然生成同一套 lifecycle objects
- **WHEN** runtime selects `BatchToolExecutor` and only observes parseable tool calls after full response completion
- **THEN** runtime SHALL still create `ToolCallEnvelope`, `ResolvedToolCall`, and `ToolOutcome` objects for those calls rather than bypassing the lifecycle model

### Requirement: Tool orchestration uses input-aware semantic lanes
The runtime SHALL classify tool calls into execution lanes using resolved semantics from normalized tool input, and SHALL allow concurrency-safe calls to run in parallel while serializing conflicting or mutating calls.

#### Scenario: 同一轮中混合并发安全与变更型工具
- **WHEN** a single turn contains multiple tool calls whose resolved semantics include both concurrency-safe calls and mutating or conflicting calls
- **THEN** runtime SHALL execute the concurrency-safe calls in parallel and SHALL serialize the mutating or conflicting calls according to the resolved lanes

### Requirement: Lane derivation degrades conservatively when precision is unavailable
The runtime SHALL derive `ToolSchedulerLane` from resolved semantics plus any available structured conflict-domain hints, and SHALL fall back to a more conservative serialized lane when it cannot derive reliable conflict information.

#### Scenario: 缺少可靠 conflict domain 时降级为串行 lane
- **WHEN** a tool call is concurrency-safe in principle but runtime cannot derive reliable conflict domains from the resolved call input or available capability data
- **THEN** runtime SHALL assign a conservative serialized lane rather than assuming safe parallel execution

### Requirement: Tool results replay in original tool_use order
The runtime SHALL commit `tool_result` blocks back into continuation history in the same order as the originating `tool_use` blocks, even if the underlying tool executions finish in a different order.

#### Scenario: 并发工具乱序完成
- **WHEN** two or more concurrently executed tools finish in a different order from the order of their originating `tool_use` blocks
- **THEN** runtime SHALL replay the resulting `tool_result` blocks in the original `tool_use` order seen by the model

### Requirement: Replay eligibility is determined by replay order, not completion order
The runtime SHALL assign replay order when `ToolCallEnvelope` objects are observed and completion order when `ToolOutcome` objects become terminal, and SHALL replay only the contiguous prefix of terminal outcomes in ascending replay order.

#### Scenario: completion 较早的 outcome 等待前序 replay slot
- **WHEN** a later tool call reaches terminal `ToolOutcome` before an earlier replay slot has become terminal
- **THEN** runtime SHALL buffer that later outcome and SHALL NOT replay it until the earlier replay slot has also become terminal

#### Scenario: progress 事件不阻塞 ordered replay
- **WHEN** a running tool emits progress updates before its terminal outcome is replay-eligible
- **THEN** runtime SHALL allow those progress events to be surfaced without treating them as replay-ordered terminal results

### Requirement: Tool outcomes preserve explicit execution status
The runtime SHALL distinguish successful execution, denied execution, cancellation, and execution failure when mapping tool outcomes back into continuation history and host-visible events.

#### Scenario: bash 非零退出码被视为执行失败
- **WHEN** a shell-like tool completes with a non-zero exit code under an error-producing failure policy
- **THEN** runtime SHALL record that tool outcome as an execution failure rather than a successful result

### Requirement: Fatal tool failures can cascade to sibling calls
The runtime SHALL support failure policies that can cancel running siblings or prevent queued siblings from starting when a fatal tool failure occurs, and SHALL preserve explicit cancellation or failure status for those affected calls.

#### Scenario: fatal tool failure 触发 sibling cancellation
- **WHEN** a tool configured with a fatal failure policy fails while sibling tool calls are running or queued in the same turn
- **THEN** runtime SHALL cancel or block those sibling calls according to the policy and SHALL emit explicit cancelled or failed tool results for them

#### Scenario: sibling cancellation 仍然占据原始 replay slot
- **WHEN** a queued or running sibling is cancelled because another tool triggered fatal failure cascade
- **THEN** runtime SHALL emit a terminal cancelled or failed `ToolOutcome` for that sibling so ordered replay can continue without gaps

### Requirement: Runtime downgrade remains observable
The runtime SHALL expose the selected tool executor tier and any runtime downgrade that occurred during the turn through metadata or turn-scoped events that hosts and tests can observe.

#### Scenario: 运行期从 full streaming 回退到 buffered
- **WHEN** runtime initially selects `FullStreamingToolExecutor` but the observed provider stream fails to deliver the promised finalize boundary behavior
- **THEN** runtime SHALL downgrade to a lower viable tier and SHALL expose both the initial tier and the effective tier in observable runtime metadata or turn events

