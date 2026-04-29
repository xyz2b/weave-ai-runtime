## Context

The runtime already has the architectural shape of a general AI runtime framework: kernel assembly, session ingress, turn execution, tool/skill/agent orchestration, host bridging, memory, and teammate control surfaces are all present. The current problem is not the absence of core capabilities; it is that the public contract still mixes kernel responsibilities, first-party capabilities, coding-agent-oriented built-ins, hook internals, and bounded compatibility shims.

That ambiguity shows up in several ways:
- `main-router`, memory, and teammate orchestration are product-critical first-party capabilities, but their implementations currently sit too close to kernel internals.
- The built-in pack still looks like one large product bundle instead of layered core versus optional official packs.
- The hook platform exposes a wider public catalog and handler surface than the framework should freeze for v1.
- Legacy compatibility seams such as `TaskManager` and shared `runtime_context` still appear too close to the primary integration story.
- Users are meant to extend `tool`, `agent`, `skill`, `host`, and `hook`, but the current docs and exports still make the internal surface feel broader than that.

The project direction is now explicit:
- it is not trying to become another Claude Code product clone;
- it is trying to converge on a reusable AI runtime framework;
- `main-router`, memory, and teammate orchestration remain first-party core capabilities;
- those capabilities may live outside the kernel package boundary as long as the runtime-owned contracts remain official and stable.

## Goals / Non-Goals

**Goals:**
- Preserve a runnable `runtime-core` that still boots with `main-router` as the default root agent.
- Introduce explicit package roles for runtime core, first-party capability packages, and higher-level full distributions.
- Keep memory and teammate orchestration as official first-party capabilities while allowing their implementations to move outside the kernel boundary.
- Reduce the stable hook surface to a smaller v1 catalog centered on lifecycle, tool, model, and host-interaction seams.
- Clarify that ordinary users extend the framework through `tool`, `agent`, `skill`, `host`, and the approved hook APIs rather than through kernel internals.
- Freeze compatibility seams as bounded migration surfaces rather than ongoing primary contracts.

**Non-Goals:**
- Remove `main-router`, memory, or teammate orchestration from the official runtime product.
- Rebuild the runtime around slash commands, plugin commands, or MCP prompt product surfaces.
- Eliminate all advanced/internal hook phases from the codebase.
- Require users to customize `TurnEngine`, `SessionController`, or low-level orchestration internals as the primary extension path.
- Redesign every built-in definition in this change; the goal is boundary convergence, not a full product reimagining.

## Decisions

### Decision: Introduce official package roles and distribution profiles

The runtime will define explicit package roles:
- `runtime-core`: kernel assembly, session/turn runtime, registries, host bridge, permissions, elicitation, core job/task control surfaces, the reduced hook SPI, and a minimal runnable built-in set.
- `runtime-memory`: the official first-party memory capability package.
- `runtime-team`: the official first-party team and teammate orchestration capability package.
- `runtime-compaction`: the official first-party context compaction package.
- `runtime-isolation`: the official first-party execution isolation package.
- `runtime-hosts-reference`: the official first-party reference host implementations package.
- `runtime-stores-file`: the official first-party file-backed store implementations package.
- `runtime-builtin-workflows`: the official first-party reusable workflow-skills package.
- optional higher-level official packs such as a workspace/devtools pack for coding-agent-oriented built-ins.
- `runtime-full`: a first-party distribution that assembles the full supported experience from the official packages.

Rationale:
- This preserves product-critical capabilities without forcing every implementation detail into the kernel package.
- It gives embedders a clean story: use `runtime-default` for the supported baseline, `runtime-full` for the full first-party experience, or assemble a narrower runtime from official packages.
- It creates a stable place to move workspace-specific built-ins without weakening the runtime's identity.

Alternatives considered:
- Keep one inseparable package: rejected because it keeps growing the kernel boundary and makes the v1 surface harder to explain.
- Move memory/team out as third-party add-ons: rejected because those capabilities remain first-party and official, not optional ecosystem extras.

### Decision: Distribution names are fixed as `runtime-core`, `runtime-default`, and `runtime-full`

The supported first-party distribution names will be fixed as:
- `runtime-core`: the minimal runnable kernel distribution
- `runtime-default`: `runtime-core` plus the first-party capability packages required for the supported product identity
- `runtime-full`: `runtime-default` plus supported mechanism, adapter, provider, and profile/workflow packages

Planned composition:

```text
runtime-core
  = kernel + root boot path

runtime-default
  = runtime-core
  + runtime-memory
  + runtime-team

runtime-full
  = runtime-default
  + runtime-compaction
  + runtime-isolation
  + runtime-openai
  + runtime-hosts-reference
  + runtime-stores-file
  + runtime-builtin-workflows
  + runtime-devtools
```

Rollout assembly view:

```text
runtime-core
  -> + runtime-memory + runtime-team
  = runtime-default
  -> + runtime-devtools
  -> + runtime-compaction + runtime-isolation
  -> + runtime-openai
  -> + runtime-hosts-reference + runtime-stores-file
  -> + runtime-builtin-workflows
  = runtime-full
```

Rollout table:

| Landing stage | Packages landing in this stage | `runtime-default` state after this stage | `runtime-full` state after this stage | Why this order |
| --- | --- | --- | --- | --- |
| Stage 1 | `runtime-core` | not complete yet | not complete yet | boot path, contracts, and compatibility boundaries must freeze first |
| Stage 2 | `runtime-memory`, `runtime-team` | complete supported baseline | inherits the supported baseline | memory and team define the first-party product identity |
| Stage 3 | `runtime-devtools` | unchanged | partial; workspace-oriented experience lands but full composition is still incomplete | move coding-oriented UX out of the kernel path early without blocking the baseline distribution |
| Stage 4 | `runtime-compaction`, `runtime-isolation` | unchanged | partial; mechanism layer lands | mechanisms have clear contracts but heavier implementation churn |
| Stage 5 | `runtime-openai`, `runtime-hosts-reference`, `runtime-stores-file` | unchanged | partial; provider and adapter layer lands | provider and environment adapters depend on the core and mechanism boundaries being explicit |
| Stage 6 | `runtime-builtin-workflows` | unchanged | complete supported full distribution | workflow packaging is safest after capability, mechanism, provider, and adapter ownership is already stable |

Rationale:
- `runtime-default` is clearer than an unnamed “supported default distribution”.
- The three names communicate three different choices: kernel only, supported product baseline, and full first-party experience.
- Fixing the names in the change avoids implementation-time drift.

Alternatives considered:
- Use only `core/full` and leave the middle distribution implicit: rejected because the supported baseline would remain ambiguous.
- Use `runtime-base` instead of `runtime-default`: rejected because “default” better communicates the supported out-of-the-box composition.

### Decision: Adopt a first-party package taxonomy instead of one flat package list

The first-party package set will be organized by role:
- capability packages: `runtime-memory`, `runtime-team`
- mechanism packages: `runtime-compaction`, `runtime-isolation`
- adapter packages: `runtime-hosts-reference`, `runtime-stores-file`, and provider integrations such as `runtime-openai`
- profile/workflow packages: `runtime-devtools`, `runtime-builtin-workflows`

First-party package layering diagram:

```text
runtime-full
├─ runtime-devtools
├─ runtime-builtin-workflows
├─ runtime-hosts-reference
├─ runtime-stores-file
├─ runtime-openai
├─ runtime-memory
├─ runtime-team
├─ runtime-compaction
├─ runtime-isolation
└─ runtime-core
```

The intended responsibility split for that diagram is:

| Package | Role | What it owns | What stays in `runtime-core` |
| --- | --- | --- | --- |
| `runtime-memory` | capability | first-party memory subsystem, memory-owned built-ins/workflows | memory service contract, assembly seam |
| `runtime-team` | capability | team control, teammate orchestration, team-owned built-ins | team-facing contracts, shared execution seams |
| `runtime-compaction` | mechanism | compaction policies, strategies, default manager implementation | prompt/private carriers, context-window contract, turn compaction slot |
| `runtime-isolation` | mechanism | worktree/remote/container-style isolation adapters | `IsolationMode`, lease contract, assembly seam |
| `runtime-hosts-reference` | adapter | CLI/SDK reference hosts and demo host implementations | host protocols, bound-host semantics |
| `runtime-stores-file` | adapter | file-backed transcript/job/task/team/workflow/mailbox stores | store protocols, config and injection seams |
| `runtime-builtin-workflows` | profile/workflow | reusable first-party workflow skills such as `verify`, `debug`, `stuck`, `batch`, `simplify` | skill contract and executor |
| `runtime-devtools` | profile/workflow | coding-agent-oriented tools, agents, and related first-party UX | root runtime boot path and control-plane core |

Supported distribution matrix:

| Distribution | Includes | Excludes by default |
| --- | --- | --- |
| `runtime-core` | kernel, root boot path, core built-ins, stable extension contracts | memory, team, compaction, isolation, provider integrations, reference hosts, file stores, workflows, devtools |
| `runtime-default` | `runtime-core` + `runtime-memory` + `runtime-team` | compaction, isolation, provider integrations, reference hosts, file stores, devtools, workflow extras |
| `runtime-full` | all supported first-party packages in this taxonomy | only packages intentionally left experimental or third-party |

Within that taxonomy:
- capability packages express product-critical runtime abilities that remain first-party and official;
- mechanism packages extend kernel execution behavior without redefining the kernel contract;
- adapter packages provide official implementations of replaceable protocols or integrations;
- profile/workflow packages provide supported higher-level user experiences without becoming kernel requirements.

Dependency rules:
- `runtime-core` owns the contracts and SHALL NOT require these packages to live inside the kernel package boundary.
- capability, mechanism, adapter, and profile packages depend on `runtime-core`.
- profile/workflow packages may optionally depend on first-party capability packages where that dependency is semantically correct, such as `remember` moving under `runtime-memory`.
- `runtime-full` depends on the supported first-party package set and remains the recommended assembled distribution.

More explicit dependency rules:

```text
runtime-core
  ├─ defines contracts, assembly seams, lifecycle ownership
  └─ has no mandatory package-layout dependency on other first-party packages

capability / mechanism / adapter / profile packages
  └─ depend on runtime-core

profile packages
  └─ may optionally depend on capability packages when the workflow semantics require it

runtime-full
  └─ composes the supported first-party package set
```

Extraction priority for the post-core split:
1. `runtime-compaction` and `runtime-isolation`, because they are important runtime mechanisms with environment- or strategy-heavy implementations.
2. `runtime-hosts-reference`, `runtime-stores-file`, and `runtime-builtin-workflows`, because they are valuable first-party modules but less central to the kernel boundary itself.

Recommended extraction waves:

| Wave | Packages | Why first/next |
| --- | --- | --- |
| Wave 1 | `runtime-compaction`, `runtime-isolation` | they are implementation-heavy mechanisms with clear kernel-facing contracts and strong reasons to evolve independently |
| Wave 2 | `runtime-hosts-reference`, `runtime-stores-file` | they are reference/adapter modules that can move cleanly once the protocol seams are explicit |
| Wave 3 | `runtime-builtin-workflows` | it is mostly packaging and ownership cleanup after capability and adapter boundaries are already stable |

Rationale:
- The taxonomy explains why not every first-party module belongs in the same package or even the same category.
- It preserves a stable kernel while still treating official memory, team, compaction, isolation, and workflow experiences as first-party.
- It gives future first-party additions a place to fit without re-opening the kernel boundary question every time.

Alternatives considered:
- Treat every official package as the same kind of “extension”: rejected because product capabilities, mechanism modules, adapters, and workflow packs have different boundary rules.
- Keep the package split informal and only describe it in docs: rejected because dependency and ownership rules need a design-level decision, not only examples.

### Decision: `main-router` stays in the core boot path

`main-router` remains part of the core built-in runtime contract and continues to be the default root agent. The runtime will not require a workspace/devtools pack just to boot a root agent.

Rationale:
- A general AI runtime still needs a first-party root routing policy.
- Removing `main-router` from the core path would make the default runtime harder to boot and harder to reason about.
- Keeping it in core does not prevent overrides; the built-in replacement contract remains the supported customization path.

Alternatives considered:
- Move `main-router` into a higher-level pack: rejected because it makes the kernel non-runnable without an extra product layer.
- Freeze `main-router` as non-replaceable: rejected because embedders must be able to override first-party routing policy through the documented built-in replacement path.

### Decision: Split built-ins into core versus official optional packs

The built-in runtime pack will become layered:
- core built-ins: runtime-generic tools and agents needed for root execution and runtime control;
- official capability-pack built-ins: memory- or team-oriented definitions that logically ship with those packages;
- official mechanism-pack built-ins where appropriate, such as compaction- or isolation-adjacent helpers that are not required for kernel boot;
- official workspace/devtools built-ins: file/web/shell-oriented tools and specialized coding-agent roles;
- official workflow-pack built-ins, primarily reusable first-party skills that are not required for core boot.

Rationale:
- The runtime should stop treating coding-agent ergonomics as the same thing as kernel identity.
- This allows the default/full distribution to remain rich without forcing the core package to carry every devtool-oriented definition.

Alternatives considered:
- Leave all built-ins in one pack and only document “core” informally: rejected because package boundaries would still be ambiguous.

Canonical built-in ownership matrix:

| Package | Built-ins owned by default |
| --- | --- |
| `runtime-core` | tools: `agent`, `skill`, `ask_user`, `sleep`, `task_create`, `task_get`, `task_update`, `task_claim`, `task_release`, `task_assign_next`, `task_block`, `task_unblock`, `task_archive`, `task_unarchive`, `task_delete`, `task_list`, `job_get`, `job_list`, `job_stop`; agents: `main-router`, `general-purpose` |
| `runtime-team` | tools: `team_create`, `team_spawn`, `team_send`, `team_respond`, `team_delete` |
| `runtime-memory` | workflows/skills: `remember` |
| `runtime-builtin-workflows` | workflows/skills: `verify`, `debug`, `stuck`, `batch`, `simplify` |
| `runtime-devtools` | tools: `read`, `glob`, `grep`, `edit`, `write`, `bash`, `web_fetch`, `web_search`; agents: `explore`, `plan`, `verification` |

Notes:
- `runtime-core` remains runnable without any first-party skills.
- `runtime-default` adds `remember` through `runtime-memory` and team tools through `runtime-team`.
- `runtime-full` adds the full first-party workflow and devtools experience.

### Decision: Keep memory and team through explicit runtime-owned contracts

Memory and teammate orchestration will remain official first-party capabilities, but the kernel will interact with them only through explicit service and assembly contracts.

Rationale:
- This preserves the product claim that agents should be able to grow and collaborate.
- It also prevents the kernel from taking direct package-layout dependencies on memory- or team-specific control-plane implementation details.

Alternatives considered:
- Keep direct imports and just move files around: rejected because it changes package layout without improving architecture.
- Remove default memory or team from the supported distribution: rejected because it weakens the intended runtime identity.

### Decision: Secondary first-party packages also move behind explicit contracts

Compaction, isolation, reference hosts, file-backed stores, and reusable built-in workflows will be treated as official first-party packages, but each one will keep a narrow kernel-facing contract:
- `runtime-compaction` owns compaction policies and strategies, while `runtime-core` retains prompt/private carriers, context-window contracts, and the turn-level compaction slot.
- `runtime-isolation` owns environment-specific isolation adapters, while `runtime-core` retains `IsolationMode`, lease contracts, and execution assembly seams.
- `runtime-hosts-reference` owns example CLI/SDK host implementations, while `runtime-core` retains host protocols and bound-host semantics.
- `runtime-stores-file` owns file-backed defaults for transcripts, jobs, task lists, teams, workflows, and teammate mailboxes, while `runtime-core` retains the store protocols and injection seams.
- `runtime-builtin-workflows` owns reusable first-party workflow skills such as `verify`, `debug`, `stuck`, `batch`, and `simplify`, while memory-specific workflows such as `remember` move under `runtime-memory`.

Rationale:
- These modules are useful first-party building blocks, but they are not all the same kind of thing.
- Narrow kernel-facing contracts make it possible to evolve implementation-heavy modules without making the kernel itself product-specific.
- The split also makes it easier to keep `runtime-core` focused on runtime ownership boundaries instead of on environment-specific or storage-specific defaults.

Alternatives considered:
- Keep these modules inside `runtime-core` until every package split is finished: rejected because it delays the boundary convergence and keeps secondary modules looking more kernel-critical than they are.

### Decision: Supported distributions publish a clear composition story

The runtime will document supported assembled distributions rather than leaving package composition implicit:
- `runtime-core`: minimal runnable kernel plus root boot path
- `runtime-default`: `runtime-core` + official capability packages required for the product identity
- `runtime-full`: `runtime-default` + supported mechanism, adapter, provider, and profile/workflow packages

This change fixes those supported distribution names and requires the composition story to be explicit and stable.

Rationale:
- Embedders need to know whether they are choosing a kernel, a product baseline, or the full first-party experience.
- A clear composition story reduces confusion when official packages move out of the kernel boundary.

Alternatives considered:
- Publish package names only and let composition remain implicit: rejected because users would still not know what the supported baseline actually includes.

### Decision: Reduce the stable hook surface and make it callback-first

The stable public hook contract will be reduced to a smaller lifecycle-oriented set: `SessionStart`, `SessionEnd`, `PreToolUse`, `PostToolUse`, `PostToolUseFailure`, `PreModelRequest`, `PostModelResponse`, `Stop`, `Notification`, `Elicitation`, and `ElicitationResult`.

Stable public registration surfaces will center on:
- runtime config hooks;
- host-bound registrations;
- skill-owned hook declarations;
- session-facing dynamic registration APIs.

The only required public handler kind for v1 will be in-process `callback`. External handler kinds (`http`, `command`, `agent`, `prompt`) may remain as advanced or package-specific surfaces, but they will no longer define the primary public promise.

Rationale:
- Ordinary framework users need a few high-value insertion points, not the full internal lifecycle graph.
- Callback-first keeps trust, recursion, and normalization semantics easier to reason about.
- Skill-owned hooks remain useful because skills are already the framework's workflow carrier.

Alternatives considered:
- Keep the full hook catalog public: rejected because it locks more of the internal main loop than v1 should freeze.
- Remove hooks entirely from the public surface: rejected because controlled lifecycle insertion remains a core framework feature.

Hook phase matrix:

| Tier | Phases | Intended use |
| --- | --- | --- |
| Stable public | `SessionStart`, `SessionEnd`, `PreToolUse`, `PostToolUse`, `PostToolUseFailure`, `PreModelRequest`, `PostModelResponse`, `Stop`, `Notification`, `Elicitation`, `ElicitationResult` | ordinary v1 extension surface |
| Advanced | `UserPromptSubmit`, `SubagentStop`, `PreCompact`, `PostCompact`, `PreContextAssemble`, `PostContextAssemble`, `RecoveryDecision` | platform/runtime specialists; not the primary portability promise |
| Internal-only | any unlisted lifecycle point | runtime implementation detail |

Registration surface matrix:

| Surface | Stability |
| --- | --- |
| runtime config hooks | stable public |
| host-bound registrations | stable public |
| skill-owned hook declarations | stable public |
| session-facing registration APIs | stable public |
| turn-scoped programmatic APIs | advanced |
| agent-owned hook declarations | compatibility/advanced only |

Required handler matrix:

| Handler kind | Status |
| --- | --- |
| `callback` | required stable public handler |
| `http`, `command`, `agent`, `prompt` | advanced or package-specific; not part of the ordinary-v1 portability promise |

### Decision: Compatibility seams stay bounded and non-authoritative

`TaskManager` and shared `runtime_context` remain migration and compatibility surfaces only. New work will continue to treat `JobService` and structured prompt/private context carriers as the authoritative contracts.

Rationale:
- The project already has the newer contracts; widening legacy seams would reverse the convergence effort.
- Explicitly bounded compatibility is easier to document, test, and eventually remove.

Alternatives considered:
- Continue dual-track support indefinitely: rejected because it would keep the wrong abstractions alive as primary integration paths.

## Risks / Trade-offs

- [Package split increases assembly complexity] → Mitigation: publish explicit package roles, keep `runtime-default` as the supported baseline and `runtime-full` as the full supported distribution, and define package registration through assembly contracts instead of late mutation.
- [Reducing the hook surface may disappoint advanced embedders] → Mitigation: keep advanced/internal phases possible behind non-primary contracts, but narrow the ordinary v1 compatibility promise.
- [Moving built-ins can create migration churn for users who depend on today's default tool pools] → Mitigation: preserve first-party `runtime-default` and `runtime-full` distributions, provide replacement/override paths, and document which definitions are core versus optional.
- [Separating memory/team implementations from kernel modules may expose hidden coupling] → Mitigation: make those dependencies explicit through service interfaces, assembly wiring, and regression tests before moving code.
- [Secondary package extraction may uncover hidden assumptions in compaction, isolation, reference hosts, or file stores] → Mitigation: first freeze the kernel-facing contracts, then move implementations one package role at a time according to the extraction priority.
- [Compatibility cleanup can surface previously hidden legacy consumers] → Mitigation: retain bounded shims, emit diagnostics for deprecated paths, and migrate docs and tests before removing integration points.

## Migration Plan

1. Publish the new package-role and distribution-profile contract in specs and docs.
2. Reclassify built-in definitions into core versus official optional packs while keeping `main-router` on the default boot path.
3. Introduce explicit assembly wiring for official memory and team capability packages.
4. Define the first-party package taxonomy and dependency rules for compaction, isolation, reference hosts, file-backed stores, and built-in workflow packs.
5. Move secondary first-party modules behind their explicit contracts in extraction-priority order.
6. Narrow the stable hook catalog, registration surfaces, and required handler kinds; update docs to present only the reduced public contract.
7. Freeze and demote legacy compatibility seams in docs and exports; keep bounded adapters and diagnostics for existing callers.
8. Keep first-party `runtime-default` and `runtime-full` distributions so users retain both a supported baseline and a full supported experience while the package boundaries converge.

Rollback strategy:
- Preserve the current monolithic distribution layout during the migration window.
- If a package split reveals hidden coupling, temporarily keep the implementation in place while retaining the new contracts and docs, then retry the physical move once the coupling is removed.
- If hook-surface narrowing causes unacceptable breakage, keep the underlying implementation but continue to treat the removed phases or handlers as advanced-only rather than restoring them to the ordinary v1 contract.

## Open Questions

- Which neutral built-in skills, if any, belong in `runtime-core` rather than in memory/team/workspace packages?
- Should `runtime-compaction` and `runtime-isolation` ship in `runtime-default` immediately, or first land as supported but opt-in first-party packages before becoming part of that baseline?
- Should advanced hook phases remain importable from the same Python package as the stable ones, or move behind an explicit advanced module path at the same time as the contract reduction?
