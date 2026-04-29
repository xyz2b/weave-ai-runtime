## Why

The runtime already exposes background-job concepts, but the current implementation is still a thin, mostly in-memory registry centered on `TaskManager`, with executor-specific logic scattered across agent dispatch, memory background work, and teammate projections. That is sufficient for simple background agents, but it is not yet a framework-grade control plane for durable, observable, stoppable long-running work that may execute agents, shell commands, or arbitrary user-defined jobs.

Now that the runtime already has a separate task-list control plane for planning, the next gap is execution control: the framework needs one generic `job` abstraction that can own lifecycle, scope, persistence, and host visibility without forcing every background-capable subsystem to invent its own registry, stop semantics, or recovery story.

## What Changes

- Introduce a runtime-owned generic job control plane with durable job records, lifecycle transitions, scoped visibility, stop/watch/query semantics, and compatibility hooks for existing runtime surfaces.
- Define a pluggable executor contract so background work can be driven by first-party executors such as `agent` and `shell`, as well as framework-embedded custom executors supplied by users or hosts.
- Split generic job records from executor-specific sidecars so the shared control plane owns lifecycle and routing, while executor-specific observability such as `AgentRunRecord`, shell output, or mailbox state remains specialized.
- Migrate current background producers such as background agents, memory extraction/consolidation, and teammate execution projections onto the new job control plane through adapters instead of direct `TaskManager` ownership.
- Upgrade built-in `job_*` tooling and host bridge surfaces to reflect the generic job model rather than the current `ManagedTask`-shaped internal registry.
- Add a staged compatibility path so the runtime can preserve existing synchronous turn execution, child-run continuation, and skill semantics while incrementally replacing internal background bookkeeping.
- **BREAKING** Deprecate `TaskManager` as the long-term primary background execution abstraction and reposition it as a compatibility facade or internal adapter during migration.

## Capabilities

### New Capabilities
- `runtime-job-control-plane`: A generic, durable job model for background execution, including executor registration, job lifecycle/state, sidecar linkage, recovery, visibility, and stop/watch/query semantics.

### Modified Capabilities
- `agent-system`: Background agent dispatch moves onto the shared job control plane while preserving agent-specific child-run records and continuation semantics.
- `builtin-runtime-pack`: Built-in `job_*` tools and background-capable first-party executors align to the generic job contract instead of the current `ManagedTask` registry shape.
- `host-runtime-bridge`: Hosts gain a unified runtime-owned surface for listing, reading, watching, and stopping jobs backed by the shared control plane.
- `memory-subsystem`: Background memory extraction and consolidation publish execution state through the shared job control plane rather than ad hoc task-manager records.
- `teammate-orchestration`: Teammate execution projections integrate with the shared job model while preserving teammate identity, mailbox lifecycle, and projection semantics.

## Impact

- Affected code: `src/runtime/tasking.py`, `src/runtime/runtime_services/__init__.py`, `src/runtime/runtime_kernel/kernel.py`, `src/runtime/hosts/base.py`, `src/runtime/agent_dispatcher.py`, `src/runtime/agent_execution*.py`, `src/runtime/builtins/tools.py`, `src/runtime/builtins/tool_impls.py`, `src/runtime/memory/manager.py`, `src/runtime/teammate_orchestration/service.py`, and related tests/docs.
- New code: job models/store/service modules, executor interfaces, sidecar linkage helpers, compatibility adapters, and host/runtime watch plumbing.
- Public/runtime contract: `job_*` remains the execution-control namespace, but its payloads and semantics become generic-job based rather than `TaskManager` internals; hosts receive a stronger job query/watch surface.
- Compatibility goal: synchronous tool execution, normal turn flow, child-run observability, and existing skill execution modes remain intact; the main blast radius is the background execution control plane, not the core conversational runtime loop.
- Follow-on work: a first-party shell executor may ship in this change or a direct follow-up, but the control plane must be designed for arbitrary executor types from day one rather than for background shell alone.
