# Persistence and State

WeaveRT keeps several kinds of durable state.
Keeping them distinct makes debugging and product integration easier.

## Who is this for?

- Readers evaluating how the runtime is assembled, executed, and persisted under the hood.

## Prerequisites

- Read `../concepts/runtime-model.md` first.
- Use the relevant concept pages as vocabulary support before treating this as the deeper architecture layer.

## Common durable artifacts

- transcripts
- child runs
- task lists and jobs
- memory artifacts
- workflow reports and host-observable diagnostics

## Typical roots

Project-local durable state often lives under `.weavert/`.
App samples may put that runtime-owned state under a higher-level local root such as `.local/examples/.../.weavert/`.

Typical examples include:

- `.weavert/transcripts/`
- `.weavert/child_runs/`
- `.weavert/task_lists/`
- `.weavert/jobs/`
- `.weavert/memory/`

Memory-specific subtrees often include:

- `.weavert/memory/documents/`
- `.weavert/memory/agents/<agent>/documents/`
- `.weavert/memory/sessions/<session>/`
- `.weavert/memory/consolidations/`

## Ownership matters more than directory names

A useful operational view is:

- the session owns transcript continuity
- delegated execution surfaces own child-run records
- memory services own memory artifacts
- the host may present or mirror state, but should not silently replace runtime authority

## Do not assume persistence is automatic

One of the easiest mistakes is assuming transcript and child-run durability always exist by default.
In practice, persistence depends on the configured stores and assembly posture.

Ask these questions explicitly:

- is there a configured transcript store?
- is there a configured child-run store?
- is the current sample using a mutable app workspace or a plain project root?

The same caution applies to memory behavior: retrieval, extraction, and consolidation posture depend on the active config and services rather than on one hard-coded global default.

## Memory and consolidation runtime

Memory persistence is not only about storing documents.
It also includes slower consolidation work that can checkpoint, stage, and merge results across closed sessions.

Typical consolidation artifacts include:

- `consolidations/checkpoints/<run-id>.json`
- `consolidations/staging/<run-id>.json`
- `consolidations/logs/<run-id>.md`
- `manifests/consolidation-manifest.json`

These artifacts help explain backlog, active locks, and whether a background merge succeeded or failed.

## Diagnostics and observability

When persistence issues involve memory, useful signals may include:

- retrieval traces
- write receipts
- background memory task ids
- config-source warnings
- `last_consolidated_at`
- durable memory deltas

## Important distinctions

- durable transcript truth is not identical to the currently projected prompt context
- runtime-private control-plane state should remain separate from model-visible context
- app-level mutable workspaces may wrap runtime-owned state, but should not obscure it

## Why users care

This separation helps you answer whether a failure came from:

- route setup
- prompt projection
- tool execution
- durable-state ownership
- host-specific wiring

## Next step

- Use `../reference/memory-configuration.md` when the next task is tuning memory retrieval or write behavior.
- Read `../guides/bind-a-host.md` if persistence questions are really about host-owned lifecycle and shutdown.
- Move to `../guides/testing-and-observability.md` when you need validation commands and observability surfaces.

## See also

- `../concepts/hosts-permissions-memory.md`
- `../concepts/memory-model.md`
- `../reference/memory-configuration.md`
- `../deep-dives/layered-memory-weavert-v2.md`
- `../../examples/apps/code_assistant/README.md`
- `../deep-dives/current-system-architecture.md`
