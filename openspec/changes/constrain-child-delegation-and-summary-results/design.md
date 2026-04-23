## Context

The runtime already has a working child execution stack: direct `agent` tool delegation, forked skill execution, sidechain `AgentRunRecord` persistence, `CHILD_RUN` turn events, and a continuation bridge that can wake waiting sessions when terminal child runs complete. That foundation is strong enough to support multi-agent flows, but two semantics remain too loose for a framework-grade default:

- delegated children can still delegate further, so nested fan-out is limited mostly by prompt behavior and tool availability instead of a runtime-owned boundary
- parent-facing child results still tend to duplicate child `messages[]`, which keeps child history outside the main transcript store but still expands the parent's working context and host payloads

This change is intentionally narrower than job control or teammate orchestration work. It does not redesign background execution ownership, child-run storage, or host watch plumbing. Instead, it tightens the contract around who may create more child runs and what shape of child result is fed back into the parent execution path.

## Goals / Non-Goals

**Goals:**

- Make child delegation depth a runtime-owned policy with a conservative default.
- Apply the same nested-delegation boundary to direct `agent` tool calls and forked skill execution.
- Make parent-facing child results summary-first by default while preserving stable child identity and terminal metadata.
- Preserve full child history in sidechain observability instead of duplicating it into parent-facing tool results.
- Upgrade child-run continuation payloads so resumed parent sessions receive summary-aware child completion context.
- Roll out the first version with a small configuration footprint that fits the existing runtime metadata policy pattern.

**Non-Goals:**

- Redesigning the shared job control plane or background executor model.
- Removing or weakening child-run observability, `CHILD_RUN` events, or `ChildRunStore` history.
- Adding another model pass just to summarize child output.
- Replacing the current `agent` / `skill` tool surface with a new dedicated task-spawn API in this change.
- Solving long-lived teammate orchestration or cross-session worker trees.

## Decisions

### 1. Delegation depth is a runtime-owned ceiling, not a prompt convention

The runtime will track a delegation depth value for child execution and enforce a ceiling before a new child run is launched. The default policy is `max_depth = 1`, meaning the root execution may create one child layer, but delegated children may not spawn more child runs unless an explicit runtime policy override raises the ceiling.

When an execution exceeds that ceiling:

- a direct `agent` tool attempt fails as a structured policy/tool error on the current execution path
- a forked skill attempt fails as a structured policy/skill error on the current execution path
- the runtime does not allocate a deeper child `run_id`, start a deeper child turn, or write a deeper child run record for the rejected spawn attempt

Why:

- termination and cost boundaries are runtime concerns, not prompt etiquette
- recursive child spawning is possible through more than one path (`agent` tool and forked skill execution), so one shared ceiling is clearer than path-specific bans
- a ceiling composes cleanly with existing parent policy inheritance and non-escalation rules

Alternatives considered:

- Ban nested delegation only through prompt instructions. Rejected because it is not enforceable and would drift by model/provider.
- Remove only the `agent` tool from child tool pools. Rejected because forked skills can still create child runs and because tool-pool presentation is not a sufficient enforcement boundary.
- Hard-code "no nesting ever" with no override. Rejected because some advanced users may need deeper worker trees, but those should require explicit opt-in.

### 2. The first rollout uses runtime metadata policy, not a brand-new top-level config object

The initial policy surface will live under `RuntimeConfig.metadata["delegation"]` and flow through `RuntimeServices.metadata`, following the existing pattern used by features such as task discipline and child-run continuation policy. Promotion to a first-class `RuntimeConfig` field is explicitly out of scope for this change and can be evaluated later if the contract stabilizes.

Why:

- it keeps the initial blast radius small
- it matches an already-established runtime policy pattern
- it lets the framework validate the behavior before freezing a bigger public config surface

Alternatives considered:

- Add a first-class `DelegationPolicyConfig` immediately. Rejected for the first iteration because the behavior needs validation before expanding the top-level config API.
- Hide the policy entirely and make it non-configurable. Rejected because advanced orchestrators may need an explicit escape hatch.

### 3. Enforcement happens in shared child execution paths, not only at call sites

The runtime will enforce the ceiling in the shared child execution path so both direct `agent` tool invocations and skill-driven fork execution observe the same rule. The built-in tool surface may still narrow presentation for user experience, but the actual rejection must happen at the shared execution boundary.

Why:

- the child execution boundary is the only place that consistently sees all spawn paths
- shared enforcement avoids divergence between `agent` tool behavior and `skill` fork behavior
- keeping the guard close to child execution reduces the risk of future spawn modes bypassing the policy

Alternatives considered:

- Enforce only in `run_agent_tool(...)`. Rejected because forked skill execution would still need a second rule path.
- Enforce only in `SkillExecutor`. Rejected because direct `agent` tool delegation would remain unconstrained.

### 4. Parent-facing child results become an explicit projection contract

The runtime will treat parent-facing child results as projections, not as the canonical child record. The default payload will expose stable child identity and terminal state plus a short summary. Full child `messages[]` remain part of sidechain observability, not the default parent-facing payload.

The intended summary-first shape is:

- `agent`
- `status`
- `background`
- `run_id`
- `parent_run_id`
- `turn_id`
- `query_source`
- `summary`
- `terminal_metadata`
- existing stable route/isolation hints when present

`summary` is always present in the parent-facing payload. Temporary detailed compatibility mode may additionally include nested child `messages`, but that mode does not remove or redefine `summary`.

Why:

- parent context hygiene is the main goal of delegation in this framework
- sidechain history already exists as the durable truth source
- separating truth from projection makes host payloads and continuation behavior easier to reason about

Alternatives considered:

- Keep returning full `messages[]` and ask parent agents to summarize later. Rejected because it defeats the whole purpose of keeping parent context small.
- Return only the last child assistant message without a stable `summary` field. Rejected because failures and denied runs would become inconsistent and callers would still need to infer projection rules.

### 5. Summary generation uses child terminal output first, then a runtime fallback

The runtime will derive the default summary from the child's terminal assistant message when one exists and is suitable. Suitability in the first rollout means:

- choose the last assistant message in the terminal child result that contains non-empty textual content
- normalize whitespace and truncate to a bounded length from runtime policy
- ignore non-text-only outputs for summary derivation

If the child ends in `failed`, `denied`, `stopped`, or otherwise lacks a usable terminal assistant message, the runtime will synthesize a short fallback summary from terminal status and metadata. The first version will not launch a second summarizer model request.

Why:

- no extra model pass means lower cost, simpler failure handling, and easier testing
- terminal assistant output already captures the child's own completion intent in the common case
- runtime fallback keeps the contract stable across failure paths

Alternatives considered:

- Always call a separate summarizer model. Rejected because it adds cost, latency, and another failure mode to every child run.
- Always use terminal metadata only. Rejected because successful child runs would lose useful semantic output.

### 6. Continuation payloads reuse the same summary projection

When a terminal child run wakes or queues a parent session through the continuation bridge, the continuation payload will carry the same summary-aware child completion context instead of only a generic "child completed" line. This keeps synchronous child results and resumed background child completions aligned.

Why:

- waiting coordinators need the child outcome, not just the fact that something ended
- summary-aware continuation avoids making resumed parents scrape child transcript text or query child state immediately
- one projection rule is easier to document and test than separate sync/background result semantics

Alternatives considered:

- Keep generic continuation text and let parents query the child later. Rejected because it weakens the main ergonomic benefit of continuation.

### 7. Compatibility rollout is staged but default-biased

The runtime will support a compatibility mode that can still include detailed child messages when explicitly enabled, but summary-first is the default behavior in this change. Repository tests, golden fixtures, and framework documentation should migrate to summary-first during this change; detailed mode exists only as an explicit migration valve for downstream callers that cannot move immediately.

Why:

- some existing callers likely depend on the current payload shape
- staged migration keeps the change adoptable without weakening the default contract

Alternatives considered:

- Hard cut directly to summary-only with no override. Rejected because it would create unnecessary churn across tests and integrations.

## Risks / Trade-offs

- [Existing callers depend on nested child `messages[]`] → Mitigation: ship an explicit migration-only compatibility flag for detailed projections and update repo-owned tests/fixtures to assert against `summary` in this change.
- [Terminal assistant output may be a poor summary] → Mitigation: normalize and truncate terminal assistant text, and synthesize runtime fallback summaries for weak or missing terminal output.
- [Metadata-backed policy is less discoverable than a first-class config field] → Mitigation: document the policy in the runtime user extension guide and revisit promotion after rollout.
- [A depth ceiling of 1 blocks advanced recursive orchestrators] → Mitigation: keep an explicit override path for higher ceilings, but require deliberate opt-in.
- [Projection and observability could drift apart] → Mitigation: keep sidechain child records and `CHILD_RUN` events as the source of truth and derive summary projection from terminal child state rather than storing a second mutable history representation.

## Migration Plan

1. Add a metadata-backed delegation policy shape under `RuntimeConfig.metadata["delegation"]` and thread delegation depth through shared child execution context.
2. Enforce the ceiling in shared child execution paths for both direct child delegation and skill forks.
3. Introduce summary-first child result projection in parent-facing serialization while preserving an explicit detailed compatibility mode that still keeps `summary` present.
4. Upgrade child-run continuation payloads to include summary-aware child completion context.
5. Update docs, tests, and golden fixtures to depend on `summary` plus child identity rather than nested child `messages[]`, and point full-history consumers at child-run observability surfaces.

Rollback strategy:

- raise or disable the delegation-depth ceiling override if nested child execution must be restored temporarily
- enable detailed child projection compatibility mode if downstream callers need the legacy payload during migration
- preserve sidechain observability regardless of rollout state so child debugging remains available

## Open Questions

None for this change. Metadata-backed delegation policy, summary-first defaults, and explicit opt-in detailed compatibility mode are the chosen rollout contract.
