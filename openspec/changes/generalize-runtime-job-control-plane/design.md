## Context

The runtime already has a functional but narrow background execution stack:

- `TaskManager` in `src/runtime/tasking.py` tracks lightweight background records and stop handlers.
- `RuntimeServices` and `ToolContext` expose that registry to runtime subsystems and built-in `job_*` tools.
- Background agents register both a `TaskManager` record and an agent-specific `AgentRunRecord` / child-run sidechain.
- Background memory extraction / consolidation and teammate execution projections also write directly into `TaskManager`.
- The built-in `bash` tool remains synchronous; there is no first-class shared background shell executor.

This architecture proved the need for background execution, but it has three structural limits for a framework:

1. the runtime has one thin internal registry, but multiple subsystems still own their own lifecycle semantics and visibility rules
2. durability, recovery, watchability, and typed linkage are inconsistent across producers
3. the abstraction boundary is too low-level for a framework that may need to run agents, shell commands, or user-defined long-running work behind the same host/runtime control surface

At the same time, the core conversational runtime is already better factored than the current background registry:

- `TurnEngine`, `SessionController`, and child-run continuation already form a distinct foreground execution loop
- `AgentRunRecord` and `CHILD_RUN` events already provide agent-specific sidecar observability
- the task-list control plane already separated planning state from execution control

The design goal is therefore not to rewrite the runtime loop. It is to replace the current ad hoc background bookkeeping with a proper framework-grade job control plane that can host multiple executor kinds while preserving existing sidecars and synchronous call paths.

## Goals / Non-Goals

**Goals:**

- Introduce a runtime-owned generic job control plane with explicit job models, lifecycle/state transitions, persistence, visibility, stop semantics, and watch/query surfaces.
- Define a pluggable executor boundary so jobs can represent agent runs, shell processes, and arbitrary user-defined background work.
- Keep executor-specific details in dedicated sidecars while making generic lifecycle and linkage visible through one shared job surface.
- Preserve the existing foreground runtime loop, child-run continuation path, and skill execution semantics.
- Provide a staged migration path from `TaskManager` to the new control plane without requiring a flag day across all subsystems.
- Keep task lists and jobs explicitly separate: tasks remain planning state; jobs remain execution control state.

**Non-Goals:**

- Replacing `TurnEngine`, `SessionController`, transcript storage, or the existing child-run continuation bridge.
- Defining a universal transport mechanism for every executor implementation; executors may use `asyncio`, threads, subprocesses, or remote backends internally.
- Making `skill` a first-class background execution mode in this change.
- Reproducing Claude Code's exact task dialog, remote-task UI, or auto-background product behavior.
- Forcing teammate lifecycle to collapse into generic job semantics; teammate identity and mailbox state remain a higher-level orchestration model.

## Decisions

### 1. Introduce a shared `JobService` and durable `JobStore`, while keeping `TaskManager` as a compatibility facade

The runtime will add a new shared job control plane composed of:

- `JobStore`: durable storage for generic job records
- `JobService`: the runtime-owned API for submit/get/list/watch/stop/update
- `JobExecutorRegistry`: executor registration and lookup
- `JobWatcher` or equivalent subscription plumbing for host/runtime consumers

`TaskManager` will not disappear immediately. During migration it becomes a compatibility facade over `JobService`, preserving existing call sites that still expect `create/get/update/list/register_stop_handler/stop_job`.

Why:

- current producers already depend on a narrow shared registry, so replacing it with another in-memory dict would not solve durability or genericity
- a compatibility facade reduces migration blast radius across agent, memory, teammate, built-in tools, and tests
- `RuntimeServices` can carry both `tasks` and `jobs` during migration, then gradually invert old callers to the new surface

Alternatives considered:

- Replace `TaskManager` in place with more fields. Rejected because it keeps a misleading shape and continues to expose implementation-specific semantics as the primary abstraction.
- Introduce a separate orchestrator per subsystem. Rejected because it repeats the same lifecycle and visibility logic in multiple places.

### 2. Model jobs as generic execution records, not as threads, subprocesses, or agents

The public runtime abstraction will be `job`, not `thread`, `process`, or `background shell`. A job record describes execution control concerns only:

```text
JobSpec
  - executor_kind
  - input payload
  - scope / visibility
  - linkage (session_id, team_id, parent_run_id, parent_turn_id)
  - control hints (stoppable, priority, policy)

JobRecord
  - job_id
  - executor_kind
  - status
  - summary / description
  - timestamps
  - visibility metadata
  - result / error envelope
  - sidecar refs
  - control capabilities
```

This keeps the control plane framework-grade. An executor may internally use:

- an `asyncio.Task`
- a subprocess
- a thread or worker pool future
- a remote backend
- a host-provided callback or custom queue

Why:

- the framework must support arbitrary user-defined long-running work, not only first-party shell or agent execution
- transport/process choices are implementation details that vary across executor kinds and deployment environments
- a job abstraction gives hosts and tools one stable control surface

Alternatives considered:

- Make shell the primary job abstraction. Rejected because the framework requirement is broader than background bash.
- Make jobs synonymous with child agents. Rejected because memory jobs and custom jobs are not agent executions.

The authoritative minimum `JobRecord` field set for the first implementation is:

- `job_id`
- `executor_kind`
- `summary`
- `description`
- `status`
- `capabilities`
- `stop_requested`
- `created_at`
- `updated_at`
- `started_at`
- `ended_at`
- `session_id`
- `team_id`
- `submitted_by`
- `projection_kind`
- `parent_run_id`
- `parent_turn_id`
- `result`
- `error`
- `metadata`
- `sidecar_refs`

The intended Python-facing sketch is:

```python
@dataclass(frozen=True, slots=True)
class JobRecord:
    job_id: str
    executor_kind: str
    summary: str
    description: str | None = None
    status: JobStatus = JobStatus.PENDING
    capabilities: JobControlCapabilities | None = None
    stop_requested: bool = False
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    started_at: datetime | None = None
    ended_at: datetime | None = None
    session_id: str | None = None
    team_id: str | None = None
    submitted_by: str | None = None
    projection_kind: str | None = None
    parent_run_id: str | None = None
    parent_turn_id: str | None = None
    result: dict[str, Any] | None = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    sidecar_refs: tuple[JobSidecarRef, ...] = ()
```

Everything else is either:

- executor-owned live state that never leaves the executor
- sidecar-owned specialized state referenced through `sidecar_refs`
- or future optional extension inside nested fields such as `capabilities` or `metadata`

### 3. Split generic job records from executor-specific sidecars

The job control plane will own generic lifecycle state, while executor-specific details remain in sidecars referenced from the job record.

Examples:

- `agent` executor sidecar: `AgentRunRecord`, child-run history, continuation metadata
- `shell` executor sidecar: stdout/stderr streaming buffers, process metadata, exit receipts
- `memory` executor sidecar: extraction/consolidation queue metadata
- `teammate` executor sidecar: mailbox claim, teammate identity, permission wait linkage

The generic job record may contain a small typed linkage envelope such as:

```text
sidecars:
  - kind: agent_run
    ref: <run_id>
  - kind: teammate_projection
    ref: <team_id>/<teammate_id>/<message_id>
```

Why:

- job consumers need common lifecycle and scope fields, not every executor's internal debug shape
- existing agent and teammate models already have richer sidechain state that should not be flattened into a lowest-common-denominator schema
- this preserves the current strength of the agent child-run model while still making job-level control uniform

Alternatives considered:

- Flatten every detail into one giant job schema. Rejected because it would quickly become executor-specific and unstable.
- Hide sidecar linkage completely. Rejected because hosts and higher-level orchestration sometimes need to correlate job state with specialized runtime records.

### 4. Custom executors register through `RuntimeConfig`, not through tool definitions

The stable embedding API for custom executors will live in runtime assembly config, not in tool definitions and not in ad hoc late mutation of runtime services.

The proposed shape is:

```text
RuntimeConfig.job_executors: dict[str, JobExecutorBinding]

JobExecutorBinding
  - executor: JobExecutor | None
  - factory: JobExecutorFactory | None
  - config: Mapping[str, Any]
  - metadata: dict[str, Any]
```

Rules:

- the dictionary key is the authoritative `executor_kind`
- exactly one of `executor` or `factory` must be provided
- built-in executor kinds such as `agent`, `shell`, `memory`, and `teammate_projection` are reserved names, but a caller may intentionally override a built-in kind by supplying the same key in `RuntimeConfig.job_executors`
- executors are infrastructure, so they are registered only through runtime config and assembly; they are not discovered from `tools/`, `agents/`, or `skills/` source trees

Factories are resolved during `_assemble_runtime_stack(...)`, after `RuntimeServices` exists but before `RuntimeAssembly` is returned. The intended factory shape is:

```text
JobExecutorFactory(
  executor_kind,
  binding,
  kernel,
  services,
) -> JobExecutor
```

This mirrors the existing style where hosts and model providers are configured during runtime assembly rather than dynamically discovered at tool-call time.

The underlying executor contract remains roughly:

```text
submit(spec, context) -> JobStartResult
stop(job_id, record, context) -> StopResult
recover(record, context) -> RecoveryResult
snapshot(record, context) -> Optional sidecar projection
```

The first implementation will follow the runtime's current style:

- immutable configuration and request/result carriers use `@dataclass(frozen=True, slots=True)`
- runtime-owned mutable services remain normal classes
- callable contracts and adapters use `Protocol`

The intended Python-facing sketch is:

```python
@dataclass(frozen=True, slots=True)
class JobExecutorBinding:
    executor: JobExecutor | None = None
    factory: JobExecutorFactory | None = None
    config: Mapping[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class JobScopeFilter:
    session_id: str | None = None
    team_id: str | None = None
    submitted_by: str | None = None
    projection_kind: str | None = None


@dataclass(frozen=True, slots=True)
class JobSubmitRequest:
    executor_kind: str
    summary: str
    input: dict[str, Any] = field(default_factory=dict)
    description: str | None = None
    session_id: str | None = None
    team_id: str | None = None
    parent_run_id: str | None = None
    parent_turn_id: str | None = None
    requested_job_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class JobExecutorContext:
    runtime_id: str
    services: RuntimeServices
    kernel: RuntimeKernel
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class JobStartResult:
    status: JobStatus
    capabilities: JobControlCapabilities | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    sidecar_refs: tuple[JobSidecarRef, ...] = ()
    result: dict[str, Any] | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class JobStopResult:
    status: JobStatus
    stop_requested: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)
    sidecar_refs: tuple[JobSidecarRef, ...] = ()
    result: dict[str, Any] | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class JobRecoveryResult:
    status: JobStatus
    capabilities: JobControlCapabilities | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    sidecar_refs: tuple[JobSidecarRef, ...] = ()
    result: dict[str, Any] | None = None
    error: str | None = None


class JobExecutor(Protocol):
    async def submit(
        self,
        request: JobSubmitRequest,
        *,
        context: JobExecutorContext,
    ) -> JobStartResult: ...

    async def stop(
        self,
        record: JobRecord,
        *,
        context: JobExecutorContext,
    ) -> JobStopResult: ...

    async def recover(
        self,
        record: JobRecord,
        *,
        context: JobExecutorContext,
    ) -> JobRecoveryResult | None: ...
```

and:

```python
class JobService(Protocol):
    async def submit(
        self,
        request: JobSubmitRequest,
        *,
        context: JobExecutorContext | None = None,
    ) -> JobRecord: ...

    async def get(
        self,
        job_id: str,
        *,
        scope: JobScopeFilter | None = None,
    ) -> JobRecord | None: ...

    async def list(
        self,
        *,
        scope: JobScopeFilter | None = None,
    ) -> tuple[JobRecord, ...]: ...

    async def watch(
        self,
        *,
        callback: Any,
        scope: JobScopeFilter | None = None,
    ) -> Any: ...

    async def stop(
        self,
        job_id: str,
        *,
        scope: JobScopeFilter | None = None,
    ) -> JobRecord: ...
```

Important boundaries for the first implementation:

- `JobSubmitRequest.input` remains an opaque payload owned by the executor kind
- `JobScopeFilter` covers the shared visibility concerns only; executor-specific filtering stays in sidecars
- `JobService.submit(...)` returns the persisted `JobRecord`, not an executor-native handle
- any live handle such as an `asyncio.Task`, subprocess object, or future remains executor-owned and is not part of the public runtime contract
- `JobExecutorBinding.factory` is the preferred hook when executor construction needs access to `RuntimeServices`, `RuntimeKernel`, or project configuration
- late manual mutation of the executor registry may exist as an internal utility, but it is not the primary embedder API

The minimal internal result contracts are intentionally patch-shaped:

- `JobStartResult` must always include `status`; everything else is optional patch data used to enrich the authoritative `JobRecord`
- `JobStopResult` must always include `status` and defaults `stop_requested=True`, so executors can represent both immediate terminal stop and accepted-but-not-yet-terminal stop
- `JobRecoveryResult` must always include reconciled `status`; returning `None` from `recover(...)` means the executor has nothing to reconcile for that record

None of these result types exposes a subprocess object, `asyncio.Task`, thread handle, or other live executor-owned object. Executors keep those internally and only project generic lifecycle patches back to `JobService`.

The shared lifecycle state machine for the first implementation is:

```text
submit:
  pending -> running | completed | failed

normal progress:
  running -> completed | failed | stopped

stop request:
  pending -> stopped
  running -> running(stop_requested=true) | stopped

recovery:
  running -> running | completed | failed | stopped

terminal:
  completed | failed | stopped -> terminal (no further lifecycle transitions)
```

This state machine is owned by `JobService`, not by individual executors. Executors propose state through `JobStartResult`, `JobStopResult`, and `JobRecoveryResult`; the shared job service validates and persists the authoritative transition.

The compatibility mapping from legacy `TaskStatus` to shared `JobStatus` is:

```text
pending   -> pending
running   -> running
completed -> completed
failed    -> failed
stopped   -> stopped
```

The inverse compatibility projection is intentionally lossy and only exists for the Stage A or Stage B adapter. New shared job semantics such as richer control capabilities or sidecar linkage are not backported into `ManagedTask`.

The canonical serialized job payload for host and tool surfaces will be shaped as:

```python
{
    "job_id": str,
    "executor_kind": str,
    "summary": str,
    "description": str | None,
    "status": str,
    "control": {
        "stoppable": bool,
        "stop_requested": bool,
    },
    "timestamps": {
        "created_at": str,
        "updated_at": str,
        "started_at": str | None,
        "ended_at": str | None,
    },
    "visibility": {
        "session_id": str | None,
        "team_id": str | None,
        "submitted_by": str | None,
        "projection_kind": str | None,
    },
    "linkage": {
        "parent_run_id": str | None,
        "parent_turn_id": str | None,
    },
    "result": dict[str, Any] | None,
    "error": str | None,
    "metadata": dict[str, Any],
    "sidecars": tuple[
        {
            "kind": str,
            "ref": str,
            "metadata": dict[str, Any],
        },
        ...,
    ],
}
```

Serialization rules:

- `job_get`, `job_list`, host `get_job`, and host `list_jobs` all use this same canonical record shape
- `job_list` and host list APIs only differ in outer container shape, not per-record field names
- executor-specific detail stays behind `sidecars[*]` refs and optional metadata rather than becoming ad hoc top-level fields
- timestamp fields are serialized once in the canonical payload instead of each surface choosing its own naming
- future additions extend nested objects such as `control`, `visibility`, or `linkage` rather than adding random top-level keys on one surface only

Key properties:

- `RuntimeConfig.job_executors` is the public embedding API
- `JobExecutorRegistry.register(...)` remains an internal/runtime-assembly convenience rather than the primary embedding contract
- executors are addressed by `executor_kind`
- tools may submit jobs, but tools are not the executor contract
- hosts/embedders may register custom executors without patching the built-in tool system

This is important for framework ergonomics. A user-defined long-running task might be launched:

- from a tool
- from a host integration
- from an orchestration service
- from future remote or scheduled control paths

Why:

- tools are model-facing invocation surfaces, not the right universal contract for background execution engines
- custom executors should be usable even when there is no model-visible built-in tool for them
- using `RuntimeConfig` keeps executor registration aligned with the current host/provider assembly model rather than introducing a second dynamic plugin path
- this keeps the control plane below tool semantics and above low-level transport

Alternatives considered:

- Encode background execution only as special tools. Rejected because not all background work originates from model-issued tool calls.
- Let each subsystem own a private executor interface. Rejected because it eliminates the benefit of a shared control plane.
- Make runtime services mutable and require callers to register executors after assembly. Rejected as the primary API because it creates ordering hazards and diverges from the current config-driven assembly style.

### 5. Preserve the core foreground runtime loop and child-run continuation as-is

The new job control plane will sit beside the main runtime loop, not inside it. The following flows remain structurally intact:

- `TurnEngine` owns foreground turn execution
- `SessionController` owns ingress and session state transitions
- `AgentExecutionService` continues to emit `AgentRunRecord` and `CHILD_RUN` events
- `ChildRunContinuationBridge` continues to decide whether terminal child runs re-enter session ingress
- `SkillExecutor` continues to use inline or fork execution semantics

Background agent submission changes only at the dispatch/control boundary:

```text
current:
  AgentDispatcher._start_background()
    -> TaskManager.create/update/stop
    -> AgentExecutionService.run()

target:
  AgentDispatcher._start_background()
    -> JobService.submit(executor_kind="agent", ...)
    -> Agent executor starts AgentExecutionService.run()
    -> sidecar linkage points to AgentRunRecord
```

Why:

- the user asked about runtime impact, and the safest path is to keep the conversational core stable
- agent continuation already uses a better abstraction than `TaskManager`
- skill semantics are only indirectly affected through shared agent/tool paths

Alternatives considered:

- Rewrite background completion as a new turn-engine state machine. Rejected because it would expand blast radius without solving the job-control problem.

### 6. Use scope-aware visibility and watcher semantics at the job layer

Jobs need the same scope clarity that task lists already gained. Each job record will carry explicit visibility metadata such as:

- `session_id`
- `team_id`
- `submitted_by`
- `owner`
- `projection_kind`
- optional `audience` or equivalent visibility class

`JobService` will expose:

- `submit(...)`
- `get(job_id, scope_filter)`
- `list(scope_filter)`
- `watch(scope_filter, callback)`
- `stop(job_id, scope_filter)`

The first watch contract will be callback-based and snapshot-oriented, matching the current task-list watch style. Hosts that only need polling can use `list/get`.

Why:

- current `TaskManager.list_visible()` already hints at scope filters; the new control plane should formalize them
- host integrations need a stable surface for monitoring long-running work
- watcher semantics belong at the job layer, not reimplemented in each executor

Alternatives considered:

- Require hosts to poll only. Rejected because some long-running work benefits from prompt updates without a custom event bus.
- Stream executor-native deltas only. Rejected for v1 because it leaks executor details into the shared contract.

### 7. Migrate producers in order of coupling: agent -> memory -> teammate, and keep shell contract-first

Migration will happen in this order:

1. Introduce `JobService` / `JobStore` / compatibility adapter
2. Move built-in `job_*` tools and host bridge to `JobService`
3. Migrate background agent dispatch, because it already has the cleanest sidecar split
4. Migrate memory background extraction/consolidation
5. Migrate teammate execution projections
6. Add first-party `shell` executor and custom executor registration examples if scope permits

Shell is important, but the control plane must not be designed around shell-specific assumptions. The initial design will make `shell` a first-class executor kind without requiring the entire rollout to be blocked on background shell UX decisions.

Why:

- agent background execution already has a strong sidecar model and clear stop semantics
- memory and teammate currently depend more directly on `TaskManager` metadata updates and need adapter time
- shell should benefit from the final abstraction, not define it prematurely

Alternatives considered:

- Start with shell and generalize later. Rejected because it would likely hardcode subprocess-centric semantics into the shared control plane.

### 8. Teammate remains a higher-level orchestrator; jobs represent execution projections, not teammate identity

Teammate orchestration will integrate with the shared job model, but teammate identity and mailbox lifecycle remain distinct from job identity.

The layering becomes:

```text
Teammate identity / mailbox / permission wait
        |
        +-- execution projection -> job record
                |
                +-- sidecar linkage -> mailbox claim / run / permission state
```

Why:

- teammate lifecycle is durable across multiple work items
- one teammate may create multiple execution projections over time
- the existing teammate spec already treats projected task surfaces as derived views, which maps naturally to job projections

Alternatives considered:

- Treat teammate itself as a long-lived job. Rejected because it confuses worker identity with one execution slot and makes mailbox recovery harder to reason about.

### 9. Keep `TaskManager` compatibility for exactly two migration stages, then remove runtime-owned dependence on it

`TaskManager` compatibility will be explicit and phased, not open-ended.

#### Stage A: bridge stage

This change introduces a `TaskManager` compatibility facade backed by `JobService`.

During Stage A:

- `RuntimeServices.task_manager`, `RuntimeAssembly.task_manager`, constructor parameters that still accept `task_manager`, and `ToolContext.task_manager` remain available
- `create/get/update/list/list_visible/register_stop_handler/unregister_stop_handler/stop_job` continue to work, but they operate as projections over the shared job control plane
- runtime-owned background producers may still pass through legacy `task_manager`-shaped seams while they are being migrated
- no new runtime capability may be designed directly against `ManagedTask` as the source of truth

Exit criteria for Stage A:

- built-in `job_*` tools are backed by `JobService`
- background agent dispatch is backed by `JobService`
- background memory jobs are backed by `JobService`
- teammate execution projections are backed by `JobService`

#### Stage B: frozen compatibility stage

Once all runtime-owned producers above are migrated, `TaskManager` remains only as a deprecated facade for legacy embedders and constructor compatibility.

During Stage B:

- `TaskManager` stays readable and stoppable
- `create/update` remain supported only to preserve legacy call sites, but the `ManagedTask` shape is frozen
- new job-plane features such as richer watcher payloads, executor capabilities, recovery hooks, and new sidecar linkage fields are exposed only through `JobService` and related shared APIs
- no runtime-owned module outside the compatibility adapter and explicit legacy tests may write new source-of-truth state through raw `TaskManager` internals

Exit criteria for Stage B:

- runtime-owned code in `src/runtime/` no longer depends on `TaskManager` for authoritative job state outside the compatibility module
- public docs and integration guidance label `TaskManager` as deprecated
- tests exist for the compatibility shim itself so removal can happen without losing regression coverage

#### Stage C: removal stage

In the follow-up cleanup change after this rollout:

- `RuntimeServices.task_manager` and other legacy injection points are removed or narrowed behind an explicit legacy adapter package
- runtime-owned constructors stop accepting `task_manager` as a primary integration path
- `JobService` becomes the only first-class background execution control surface

Why:

- the current codebase still has multiple constructor seams and helper contexts that mention `task_manager`, so immediate removal would create unnecessary blast radius
- leaving compatibility open-ended would encourage new code to keep depending on the wrong abstraction
- stage-based exit criteria make it clear when the project is allowed to stop widening the legacy surface

Alternatives considered:

- Keep `TaskManager` indefinitely as a parallel public abstraction. Rejected because it would permanently split the control plane.
- Remove `TaskManager` in the same patch that introduces `JobService`. Rejected because too many runtime-owned modules still depend on task-manager-shaped seams today.

## Risks / Trade-offs

- [Two overlapping APIs during migration] -> Mitigation: keep `TaskManager` as an explicitly deprecated compatibility facade, document that `JobService` is authoritative, and convert runtime-owned call sites in phases.
- [Durable store adds complexity] -> Mitigation: use the same conservative file-backed patterns already used by task lists and teammate mailbox state, and keep the generic schema minimal.
- [Executor leakage into the shared schema] -> Mitigation: allow only common lifecycle/linkage fields in `JobRecord`; move detailed executor state into typed sidecars.
- [Stop semantics vary across executors] -> Mitigation: make stoppability an explicit capability on each job record and standardize the shared result contract for `not_found`, `not_running`, and `not_stoppable`.
- [Host expectations drift from executor reality] -> Mitigation: expose snapshot-oriented generic job state plus explicit sidecar refs instead of inventing synthetic per-executor fields in the shared contract.
- [Teammate migration may destabilize mailbox recovery] -> Mitigation: migrate teammate last and preserve mailbox snapshotting as the source of truth, with jobs as execution projections only.

## Migration Plan

1. Add the foundational modules:
   - `JobRecord` / `JobStatus` / `JobSpec`
   - `JobStore`
   - `JobService`
   - `JobExecutorRegistry`
   - `RuntimeConfig.job_executors` and `JobExecutorBinding`
   - compatibility adapter from `TaskManager` to `JobService`
2. Extend `RuntimeServices`, runtime assembly, and host bridge wiring to expose the new job service, instantiate configured executor bindings, and preserve current task-manager-shaped fields for Stage A compatibility.
3. Move built-in `job_get`, `job_list`, and `job_stop` to `JobService`; keep payload compatibility where feasible but treat `JobRecord` as the new source of truth.
4. Introduce the first-party `agent` executor and migrate `AgentDispatcher._start_background()` to submit jobs through the shared plane while keeping `AgentRunRecord` and child-run continuation unchanged.
5. Migrate background memory extraction/consolidation to job projections with memory-specific sidecar metadata.
6. Migrate teammate execution projections so active executions are represented as jobs while teammate mailbox state remains durable and authoritative.
7. If included in scope, add a first-party `shell` executor and an example custom executor registration path for embedders using `RuntimeConfig.job_executors`.
8. Freeze Stage B compatibility: keep `TaskManager` only as a deprecated facade, stop adding new job semantics to `ManagedTask`, and remove remaining runtime-owned authoritative dependencies on the legacy surface.
9. In the follow-up cleanup change, remove Stage C legacy injection points after the frozen compatibility criteria are met.

Rollback strategy:

- revert producers back to the compatibility facade while leaving `JobService` disabled
- keep existing child-run continuation and teammate mailbox state intact because they remain separate sidecars
- preserve `job_*` read surfaces by projecting from the compatibility layer if a subsystem-specific migration needs to be rolled back

## Open Questions

- None for the first proposal draft. The design resolves the key architectural defaults as follows: `job` is the shared abstraction, executors are pluggable and runtime-registered, sidecars stay specialized, `TaskManager` becomes a compatibility layer, and core foreground runtime semantics remain unchanged.
