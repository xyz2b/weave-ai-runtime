# Workflow Observability Reference

This page summarizes the shared workflow observability model exposed by the runtime.

## Who is this for?

- Readers who already know the workflow and now need a stable lookup page.

## Prerequisites

- Read the matching guide or concept page first.
- Treat this page as a reference sheet, not the first-stop tutorial.

## Core objects

- `WorkflowRunIdentity`
  - stable `run_id`, `session_id`, and `turn_id`
- `WorkflowRunLinkage`
  - parent run or parent turn correlation
- `WorkflowRunObservability`
  - run kind, lifecycle status, outcome, linkage, and structured diagnostics
- `WorkflowDiagnostic`
  - diagnostic severity and outcome semantics
- `WorkflowObservationEvent`
  - event-shaped projection for hosts and streams

## Lifecycle status vocabulary

- `running`
- `completed`
- `max_turns`
- `blocked`
- `interrupted`
- `failed`
- `denied`
- `stopped`

## Outcome vocabulary

- `running`
- `succeeded`
- `degraded`
- `blocked`
- `interrupted`
- `failed`

## Diagnostic severity vocabulary

- `info`
- `advisory`
- `blocking`

## Where the model appears

### Turn streams

Workflow observations appear on turn-stream events such as:

- `event.workflow_observation`
- `event.metadata["workflow_observation"]`

### Child-run projections

Child-run helpers expose the same model through projected records and results.

### Host bridge

The runtime emits workflow extension events through `HostRuntime.emit_extension_event(...)` under namespace `weavert.workflow`.
Typical event types include:

- `workflow.started`
- `workflow.terminal`
- `workflow.child.updated`

### Workflow reports and helpers

`WorkflowRunReport` and helpers such as `terminal_failure(...)`, `child_summary(...)`, and `resolve_workflow_run_observability(...)` preserve the same shared model.

## Interpret the model correctly

Use the shared model when you need one runtime-owned answer to questions like:

- what workflow run is this?
- what state is it in?
- is it healthy, degraded, blocked, or failed?

Use raw turn streams, transcripts, or durable child-run records when you need lower-level truth.

## Next step

- Return to `../guides/testing-and-observability.md` for the broader validation workflow around these fields.
- Read `../architecture/request-lifecycle.md` if you want to map the observability terms back onto runtime phases.

## See also

- `../guides/testing-and-observability.md`
- `../architecture/request-lifecycle.md`
- `../deep-dives/weavert-workflow-observability.md`
