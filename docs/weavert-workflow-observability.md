# WeaveRT Workflow Observability

The runtime now exposes one shared workflow observability model across the existing workflow execution surfaces. The goal is to keep the low-level truth surfaces intact while giving callers a stable runtime-owned interpretation layer for workflow identity, lifecycle, linkage, and diagnostics.

## Shared model

The shared model lives in `weavert.workflow_observability` and centers on:

- `WorkflowRunIdentity` for stable `run_id`, `session_id`, and `turn_id`
- `WorkflowRunLinkage` for parent run or parent turn correlation
- `WorkflowRunObservability` for shared run kind, lifecycle status, outcome, linkage, and structured diagnostics
- `WorkflowDiagnostic` for stable diagnostic severity and outcome semantics
- `WorkflowObservationEvent` for event-shaped projections used by turn streams and the host bridge

### Stable vocabulary

Lifecycle status values:

- `running`
- `completed`
- `max_turns`
- `blocked`
- `interrupted`
- `failed`
- `denied`
- `stopped`

Outcome values:

- `running`
- `succeeded`
- `degraded`
- `blocked`
- `interrupted`
- `failed`

Diagnostic severity values:

- `info`
- `advisory`
- `blocking`

The runtime uses that vocabulary consistently when it projects successful completion, advisory degradation such as `max_turns`, blocking cases such as permission denial, and terminal failures.

## Relationship to raw turn streams

Raw turn-stream events still describe the step-by-step execution of a turn. They now also carry a unified workflow observation in two places:

- `event.workflow_observation` on the `TurnStreamEvent`
- `event.metadata["workflow_observation"]` for metadata-oriented consumers

That shared observation gives hosts and callers one workflow identity and diagnostic contract without removing any request, tool, message, or terminal detail from the original stream.

## Relationship to child-run records

`AgentRunRecord` remains the durable child-run truth surface. Child-run projection helpers now expose the same shared workflow model alongside the existing child summary fields:

- `project_child_run_record(record)["workflow_observability"]`
- `project_agent_run_result(result)["workflow_observability"]`

That means callers can keep using the existing child-run payloads while also reading stable shared lifecycle and diagnostic semantics for delegated work.

## Relationship to the host bridge

Bound hosts can continue consuming raw turn events and extension events. The runtime now emits unified workflow host events through `HostRuntime.emit_extension_event(...)` with:

- namespace: `weavert.workflow`
- schema version: `1.0`
- event types:
  - `workflow.started`
  - `workflow.terminal`
  - `workflow.child.updated`

The event payload is the serialized `WorkflowObservationEvent`. Hosts no longer need to reconstruct authoritative workflow state only from unrelated turn, notification, or child-specific side channels.

## Relationship to workflow run reports and result helpers

`WorkflowRunReport` now carries:

- `turn_id`
- `run_id`
- `workflow_observability`

Higher-level helpers preserve that same shared model:

- `terminal_failure(report).workflow_observability`
- `child_summary(...).workflow_observability`
- `resolve_workflow_run_observability(...)`

These helpers remain convenience layers, but they now preserve the runtime's shared workflow semantics instead of inventing report-local or projection-local lifecycle meanings.

## Low-level truth still wins

The unified model is intentionally additive. If you need low-level execution facts, use the raw turn stream, transcript messages, or durable child-run records. If you need one runtime-owned answer to “what workflow run is this, what state is it in, and how healthy is it?”, use the shared workflow observability model.
