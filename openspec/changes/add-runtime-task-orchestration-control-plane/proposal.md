## Why

当前 runtime 已经把 planning task list、background job registry 和 typed child-run observability 分开了，但任务编排语义仍然不完整：`blocks` / `blocked_by` 主要还是存储字段，`claim` 没有成为模型可用的原子调度操作，available task 需要模型自己推断，background child run 的 terminal 结果虽然可观测，却不会稳定地进入主 session 的 continuation policy。结果是，多 agent 工作流仍然过度依赖 prompt discipline，而不是 runtime 自身提供的 orchestration contract。

这个缺口现在已经开始影响上层能力的一致性。任务依赖可能被绕过或双向边漂移，waiting coordinator 不会因为 child run 结束而自动续跑，host 和模型各自重复实现“什么任务可做”的判断逻辑。下一步需要把任务编排从“task list persistence + prompt reminder”提升为真正的 runtime control plane。

## What Changes

- Add a runtime-owned task orchestration control plane on top of the existing task list service, formalizing `claim`, `release`, `assign_next`, dependency-edge maintenance, and task-availability derivation as first-class runtime semantics.
- Introduce blocker-aware atomic claim semantics with optional owner-busy enforcement, instead of treating task ownership updates as generic mutable fields.
- Replace raw `blocks` / `blocked_by` patching with dedicated dependency operations that maintain forward and reverse edges together, reject cycles, and clean dangling edges on delete.
- Expose derived task-list views such as `available`, `blocked`, `in_progress`, and unresolved blockers so models, hosts, and runtime automation do not each need to recompute readiness independently.
- Extend the built-in task tool surface with orchestration-aware operations such as `task_claim`, `task_release`, `task_assign_next`, `task_block`, and `task_unblock`.
- **BREAKING**: narrow `task_update` so orchestration-critical fields no longer rely on raw patch semantics; dependency edges and claim/assignment flow through dedicated control-plane operations instead of arbitrary `task_update` payloads.
- Add a child-run continuation bridge that turns terminal child-run lifecycle into structured session ingress events when policy allows, so background or delegated completions can wake a waiting coordinator without introducing XML transcript protocols.
- Preserve typed `CHILD_RUN` turn-stream events as the primary host/SDK observability surface; continuation admission is layered runtime policy, not a replacement for typed child-run records.

## Capabilities

### New Capabilities
- `task-orchestration-control-plane`: runtime-owned task-graph orchestration semantics, including claim/release/assign-next operations, dependency-edge helpers, and derived availability views for execution readiness.

### Modified Capabilities
- `builtin-runtime-pack`: built-in task tools gain orchestration-aware operations, and generic task mutation is narrowed so dependency edges and claims flow through dedicated control-plane APIs.
- `child-run-observability`: terminal child-run records remain typed observability artifacts but can additionally drive structured continuation signals for parent sessions.
- `runtime-session-ingress`: task-generated continuation inputs can be admitted as turns by explicit ingress policy instead of remaining transcript-only by default.
- `host-runtime-bridge`: hosts continue to consume typed task-list and child-run state while runtime retains ownership of orchestration and continuation policy.

## Impact

- Affected code: `src/runtime/task_lists.py`, `src/runtime/builtins/tools.py`, `src/runtime/builtins/tool_impls.py`, `src/runtime/runtime_services/__init__.py`, `src/runtime/agent_execution_service.py`, `src/runtime/session_runtime/controller.py`, `src/runtime/session_runtime/ingress.py`, `src/runtime/runtime_kernel/kernel.py`, and `src/runtime/task_discipline.py`.
- New code: task-orchestration view models and error types, a child-run continuation bridge, a live session registry or equivalent continuation-target registry, and supporting tests for dependency validation and continuation admission.
- Built-in API surface: `task_*` grows dedicated orchestration operations, `task_update` loses orchestration-heavy raw patch responsibilities, and task-list responses gain derived readiness data for hosts and models.
- Runtime behavior: waiting sessions can resume from structured child-run completion signals under explicit policy, and task dependency enforcement moves from prompt discipline into runtime-owned atomic control-plane logic.
- Testing and documentation: task orchestration docs, built-in tool contracts, host/runtime bridge docs, and multi-agent continuation tests need updates to cover dependency enforcement, derived availability, and child-run-driven continuation.
