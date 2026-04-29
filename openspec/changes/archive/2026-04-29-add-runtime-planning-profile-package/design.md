## Context

The runtime already has a runtime-owned planning control plane: shared task lists, job inspection, host bridge methods, derived readiness/orchestration views, and task-discipline sidecar behavior all sit on the core runtime path. At the same time, the first-party package taxonomy now distinguishes core contracts from higher-level first-party experiences such as `runtime-devtools` and `runtime-builtin-workflows`.

What is still missing is a canonical package boundary for planner UX. The docs already describe `planner`, `coordinator`, and `worker` as first-class profile ideas, but the codebase does not yet offer a first-party package that owns those profiles. The current `plan` built-in agent in `runtime-devtools` is closer to a read-only execution-planning helper than to a runtime-owned shared-planning profile, so it does not fill that gap.

The main constraint is architectural: this change must not weaken the current runtime-core contract. Shared planning state and task/job semantics are already treated as framework primitives, and hosts rely on those semantics independently of any planner-specific agent experience.

## Goals / Non-Goals

**Goals:**
- Introduce `runtime-planning` as an official first-party profile/workflow package.
- Define a stable ownership boundary between planning control-plane primitives and planning-oriented first-party agent/profile UX.
- Add canonical first-party planning profiles such as `planner`, `coordinator`, and `worker`.
- Keep `runtime-default` unchanged while making `runtime-full` include the planning package.
- Preserve ordinary built-in discovery, replacement, and visibility rules for planning profiles.
- Provide a compatibility story for current users of the `plan` agent and ad hoc planner prompts.

**Non-Goals:**
- Move `TaskListService`, `task_*`, `job_*`, host task/job bridge methods, or readiness/orchestration semantics out of `runtime-core`.
- Reclassify planning as a capability or mechanism package.
- Require `runtime-planning` just to keep `runtime-core` or `runtime-default` conformant.
- Redesign the task/job public contracts in this change.
- Extract every planning-adjacent policy or sidecar out of core in the first landing.

## Decisions

### Decision: `runtime-planning` is a profile/workflow package, not a capability package

`runtime-planning` will be classified alongside `runtime-devtools` and `runtime-builtin-workflows` as a higher-level first-party profile/workflow package. It represents an official way to package planner-oriented agent behavior and workflow assets, not a new runtime primitive.

Rationale:
- planning control surfaces already exist in the framework core;
- the missing piece is packaged first-party UX, not a missing kernel capability;
- putting `runtime-planning` in the profile/workflow tier preserves the existing package taxonomy.

Alternatives considered:
- make `runtime-planning` a capability package: rejected because it would imply that shared planning semantics belong outside core;
- fold planner UX into `runtime-devtools`: rejected because planning-state ownership and workspace/devtool ergonomics are separate concerns.

### Decision: Planning control-plane ownership remains in `runtime-core`

This change will keep `TaskListService`, `task_*`, `job_*`, task/job host bridge surfaces, and derived orchestration/readiness semantics in `runtime-core`. `runtime-planning` consumes those primitives through ordinary runtime assembly and tool-pool resolution instead of redefining them.

Rationale:
- task/job semantics are already documented as framework primitives rather than planner-private behavior;
- host APIs and runtime services depend on those semantics even when no planner profile is installed;
- the current codebase has a store seam for task persistence but not yet a distinct package seam for task-list service ownership, so a full control-plane extraction would create churn without buying meaningful modularity.

Alternatives considered:
- move the whole planning subsystem behind `runtime-planning`: rejected because it would weaken the core contract and blur the distinction between runtime primitives and first-party UX;
- split only storage from core: already effectively handled by `runtime-stores-file`, so it does not address the planner-profile packaging gap.

### Decision: `runtime-planning` owns canonical planner/coordinator/worker profiles

The first landing of `runtime-planning` will define official built-in agent profiles such as:
- `planner`: shared task-list maintenance and decomposition profile centered on `task_*`
- `coordinator`: shared planning plus execution-observation profile centered on `task_*`, `job_*`, and core orchestration surfaces such as `agent`
- `worker`: execution-focused profile that can participate in coordinated workflows without being forced to own the shared task list

These profiles will be registered through the same built-in discovery, replacement, and visibility rules as other first-party agents.

Rationale:
- the docs already describe these as the preferred official mental model;
- packaging them as first-party profiles gives embedders a stable baseline they can override rather than re-create from scratch;
- keeping the definitions in a dedicated package prevents planner UX from being implied only by docs or mixed into unrelated devtools bundles.

Alternatives considered:
- expose only prompt snippets or docs, not built-in profiles: rejected because the package would not materially change the runtime assembly story;
- ship only one generic `planner` profile: rejected because `planner`, `coordinator`, and `worker` reflect materially different tool-pool and responsibility boundaries.

### Decision: `runtime-full` includes `runtime-planning`; `runtime-default` does not

`runtime-default` will remain the supported baseline of `runtime-core + runtime-memory + runtime-team`. `runtime-full` will add `runtime-planning` alongside the other higher-level first-party packages.

Rationale:
- planning profiles are valuable first-party UX but not required for the minimal supported product identity;
- this preserves the current contract that `runtime-default` focuses on core runtime capabilities rather than higher-level workflow packs;
- `runtime-full` is the correct place for official planner UX to land by default.

Alternatives considered:
- add `runtime-planning` to `runtime-default`: rejected because it would widen the baseline distribution with optional UX profiles;
- keep `runtime-planning` opt-in only and omit it from `runtime-full`: rejected because the full distribution is supposed to carry the official first-party experience.

### Decision: The existing `plan` agent remains in `runtime-devtools` for now

This change will not reinterpret the current `plan` agent as the canonical shared-planning profile. Instead, `runtime-planning` will introduce `planner` / `coordinator` / `worker` as new first-party profiles, while `plan` remains a devtools-oriented read-only planning helper unless a later cleanup explicitly deprecates or relocates it.

Rationale:
- the current `plan` agent is already established as a lightweight read-only helper in `runtime-devtools`;
- reusing its name for task-list-owned coordination would create unnecessary compatibility risk and semantic drift;
- adding explicit planning-profile names is clearer than silently changing the meaning of `plan`.

Alternatives considered:
- move `plan` directly into `runtime-planning`: rejected for the first landing because it would couple package cleanup to a behavior and naming migration;
- deprecate `plan` immediately: rejected because users may still rely on it as a lightweight analysis helper.

### Decision: Task-discipline sidecar stays in core for the first landing

The current task-discipline sidecar and related runtime-owned policy metadata will remain in core for this change. `runtime-planning` may later absorb optional higher-level planning policies once the package and service seams are more mature, but the first landing will focus on profile ownership rather than policy extraction.

Rationale:
- the sidecar currently behaves as a host-agnostic runtime policy layer, not merely a profile prompt asset;
- moving it now would broaden scope into control-plane ownership questions that this package-boundary change does not need to solve;
- the first useful milestone is a clean official planning-profile package, not a full policy refactor.

Alternatives considered:
- move task-discipline into `runtime-planning` immediately: rejected because it expands the change from profile packaging into runtime-policy relocation;
- freeze task-discipline as permanently core-owned: rejected because future profile-owned policy overlays may still make sense once seams improve.

## Risks / Trade-offs

- [Two planning-related first-party surfaces may confuse users at first] → Mitigation: document the distinction clearly: `plan` is a devtools helper, while `planner` / `coordinator` / `worker` are shared-planning profiles.
- [A new package without strong profile semantics could become a thin wrapper] → Mitigation: require canonical first-party profile definitions and package ownership metadata, not just docs.
- [Users may expect `runtime-planning` to own task/job primitives] → Mitigation: state normatively that those primitives remain in `runtime-core` and keep the host/runtime bridges unchanged.
- [Task-discipline staying in core may feel inconsistent with planner UX packaging] → Mitigation: document it as an intentional first-landing boundary and leave a follow-up path for optional policy extraction.

## Migration Plan

1. Add `runtime-planning` to the first-party package taxonomy and supported distribution composition, with `runtime-full` including it and `runtime-default` unchanged.
2. Create the package-owned planning definitions and register them through ordinary built-in loading and package ownership metadata.
3. Update built-in ownership docs, runtime package catalogs, and diagnostics to surface the new package and its canonical profile ownership.
4. Add migration notes that distinguish the existing `plan` helper from the new planning profiles, and document when embedders should choose each.
5. Add regression coverage for package selection, planning profile discovery, ownership metadata, and `runtime-full` composition.

Rollback strategy:
- `runtime-planning` can be disabled as a higher-level package without weakening the underlying `task_*` / `job_*` core contract;
- `runtime-full` composition can temporarily drop the package while preserving all planning control-plane primitives in `runtime-core`.

## Open Questions

- Should a later follow-up add package-owned planning skills or prompt assets beyond built-in agent profiles, or is agent-profile ownership sufficient for the first stable `runtime-planning` boundary?
