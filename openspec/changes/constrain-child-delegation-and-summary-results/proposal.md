## Why

The runtime already supports delegated child execution and sidechain child-run observability, but delegated children can still delegate further and parent-facing tool results still duplicate child `messages[]` back into the parent turn. That makes multi-agent execution harder to bound, easier to recurse accidentally, and more likely to bloat parent context even when the child already has its own sidechain history.

Now that the runtime already has durable child-run records and continuation plumbing, it should treat delegation boundaries and parent-visible child results as runtime-owned control-plane semantics instead of prompt discipline. The framework needs a conservative default that keeps child execution observable without letting recursive delegation and transcript duplication become the default behavior.

## What Changes

- Add a runtime-owned delegation-depth policy for child execution, with a conservative default that allows root-to-child delegation but prevents delegated children from spawning further child runs.
- Apply the same delegation-depth ceiling to direct `agent` tool delegation and forked skill execution so skill forks cannot bypass the child delegation boundary.
- Reject over-depth child spawn attempts as structured delegation policy errors on the current execution path instead of silently relying on prompt discipline or allocating a deeper child run anyway.
- Change the default parent-facing child result contract to return stable identity, terminal status, and summary instead of full child `messages[]`, and keep `summary` present even when a temporary detailed compatibility mode is enabled.
- Preserve full child message history in sidechain child-run observability and query surfaces rather than duplicating that history into parent-facing tool results.
- Extend child-run continuation delivery so waiting coordinators receive summary-aware child completion context instead of only a generic terminal notification.
- Fix the first rollout on a metadata-backed runtime policy surface under `RuntimeConfig.metadata["delegation"]`, while leaving first-class config promotion to a later follow-up if the contract proves stable.
- Keep room for explicit runtime configuration overrides, but make bounded delegation and summary-first parent projection the framework default.
- **BREAKING**: the default built-in `agent` tool result contract no longer requires full child `messages[]` in parent-facing payloads; child results become summary-projected by default.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `agent-system`: child execution gains a runtime-owned delegation-depth ceiling and a summary-projected parent-facing result model.
- `agent-delegation`: the built-in `agent` tool changes its default child result contract from full message replay to summary-first projection.
- `child-run-observability`: child sidechain history remains the source of truth while parent-facing results become a separate projection contract.
- `skill-policy-semantics`: forked skill execution is constrained by the same delegation-depth ceiling as direct child agent execution.
- `skill-runtime-semantics`: forked skill results reuse the same summary-first child result projection contract as direct `agent` tool delegation.
- `runtime-session-ingress`: child-run continuation inputs carry summary-aware completion context for resumed parent sessions.

## Impact

- Affected code: `src/runtime/agent_execution_service.py`, `src/runtime/agent_dispatcher.py`, `src/runtime/runtime_kernel/kernel.py`, `src/runtime/skill_runtime.py`, `src/runtime/child_run_continuation.py`, `src/runtime/execution_policy.py`, and related tests/docs.
- Public/runtime contract: parent-facing child results for delegated execution become summary-first by default, while full child history remains available through sidechain observability rather than transcript duplication.
- Configuration surface: this change fixes the first rollout on `RuntimeConfig.metadata["delegation"]` / `RuntimeServices.metadata["delegation"]`; first-class config promotion is explicitly deferred.
- Migration surface: callers that still need full child history must move to child-run observability surfaces such as runtime child-run records/query paths and `CHILD_RUN` turn events instead of parent-facing tool-result duplication.
- Compatibility risk: tests, golden fixtures, and any callers that currently depend on nested child `messages[]` in `agent` tool results or forked skill `agent_result` payloads will need to migrate to `summary` plus child-run observability, using detailed projection mode only as an explicit migration valve.
