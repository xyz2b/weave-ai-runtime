# WeaveRT Runtime Boundary Migration Ledger

> Documentation note: This file remains the detailed migration ledger for runtime-boundary changes. Start with `docs/maintainers/migration-notes.md` for the maintainer-facing index.

This maintainer reference keeps the migration ledger itself: old default built-ins, older hook surfaces, older first-party package layout, canonical import-root tightening, and the diagnostics or compatibility clues that point to each migration.

Primary docs path:

- Maintainer migration index -> `docs/maintainers/migration-notes.md`
- Package system -> `docs/architecture/package-system.md`
- Testing and observability -> `docs/guides/testing-and-observability.md`

Use this page when you already know the new docs path and need to answer "where should the old integration move?", "which diagnostics are migration hints?", or "which compatibility surfaces have been tightened?"

## 1. Project position

Treat this project as a **general AI runtime framework**, not a Claude Code parity effort.

A useful top-level model is three distribution layers:

- `weavert-core`
- `weavert-default`
- `weavert-full`

and four first-party package roles:

- capability: `weavert-memory`, `weavert-team`
- mechanism: `weavert-compaction`, `weavert-isolation`
- adapter / provider: `weavert-hosts-reference`, `weavert-stores-file`, `weavert-openai`
- profile / workflow: `weavert-devtools`, `weavert-builtin-workflows`, `weavert-planning`

One additional fact still matters here:

- `planner` / `coordinator` / `worker` now ship from the standalone `weavert-planning` package
- `weavert-full` assembles them automatically; `weavert-default` does not
- the existing read-only planning helper `plan` still remains in `weavert-devtools`

## 1.5 Canonical Import Root Boundary

You now need to separate "canonical import" from "selected package" completely:

- `weavert` remains the runtime core surface
- extracted first-party families now use their own package roots such as `weavert_openai`, `weavert_memory`, `weavert_team`, and `weavert_hosts_reference`
- distribution, `enabled_packages`, and `disabled_packages` decide whether those add-ons participate in runtime assembly

This means the old core-namespace projection is no longer the recommended compatibility path. If you still use imports like these, migrate them:

- `weavert.openai_client` -> `weavert_openai.openai_client`
- `weavert.memory.manager` -> `weavert_memory.manager`
- `weavert.hosts.reference` -> `weavert_hosts_reference`
- `weavert.team.assembly` -> `weavert_team.assembly`

## 2. Workspace / Devtools Built-ins

In older versions, workspace-oriented tools and coding agents were often treated as always present. They now belong to `weavert-devtools` and are auto-enabled only in `weavert-full`.

Affected built-ins include:

- tools: `read`, `glob`, `grep`, `edit`, `write`, `bash`, `web_fetch`, `web_search`
- agents: `explore`, `plan`, `verification`

If you previously relied on these built-ins by default, there are two compatibility paths:

1. use `RuntimeDistribution.FULL` directly
2. keep the current distribution but enable `weavert-devtools` explicitly

The runtime now provides two migration hints:

- `runtime_devtools_not_selected` inside `weavert.kernel.diagnostics`
- the `devtools` entry inside `weavert.services.metadata["migration"]`

## 2.5 Planning Profile Terminology

The easiest confusion right now is not the task/job contract but the planning-profile names.

Use the following terminology:

- `plan`
  - the currently bundled and directly discoverable agent
  - belongs to `weavert-devtools`
  - behaves more like a read-only analysis, step-breakdown, and pre-implementation planning helper
- `planner`
  - the official shared task-list maintenance profile from `weavert-planning`
- `coordinator`
  - the official `task_* + job_*` coordination profile from `weavert-planning`
- `worker`
  - the official execution profile from `weavert-planning`
  - does not own the shared task list by default and does not automatically receive optional devtools or team tools

This means:

- there is no hard migration step that automatically maps old `plan` onto one deployed `planner` package
- if you need a read-only analysis helper, continue treating `plan` as a `weavert-devtools` built-in
- if you need a shared planning workflow, prefer `planner` / `coordinator` / `worker` from `weavert-planning`, then apply agent replacement or project override as needed

## 3. Hook Surface Tightening

Stable public hook phases now keep only the ordinary-v1 set:

- `SessionStart`
- `SessionEnd`
- `PreToolUse`
- `PostToolUse`
- `PostToolUseFailure`
- `PreModelRequest`
- `PostModelResponse`
- `Stop`
- `Notification`
- `Elicitation`
- `ElicitationResult`

The following phases still exist, but they should be treated as advanced contracts rather than ordinary platform-portability promises:

- `UserPromptSubmit`
- `SubagentStop`
- `PreCompact`
- `PostCompact`
- `PreContextAssemble`
- `PostContextAssemble`
- `RecoveryDecision`

The only stable public handler kind now is:

- `callback`

The following handler kinds should now be treated only as advanced or package-specific surfaces:

- `http`
- `command`
- `agent`
- `prompt`

This structured information is also exposed through `weavert.services.metadata["migration"]["hook_contract"]`.

## 4. First-Party Package Ownership Changes

The following capability ownership should now be understood by package, not by internal kernel file layout:

- `remember` -> `weavert-memory`
- `team_create` / `team_spawn` / `team_send` / `team_respond` / `team_delete` -> `weavert-team`
- `verify` / `debug` / `stuck` / `batch` / `simplify` -> `weavert-builtin-workflows`
- bundled default OpenAI live adapter -> `weavert-openai`
- reference host implementations -> `weavert-hosts-reference`
- file-backed transcript / job / task-list / team / workflow / mailbox stores -> `weavert-stores-file`

One semantic change matters especially here:

- `openai_default` is still the default route name
- but it is now a tool-capable Responses adapter rather than the old minimal baseline
- during migration, do not keep assuming the bundled OpenAI path can only do text bootstrap

For planning, package ownership is now explicit:

- shared planning primitives should still be understood as owned by `weavert-core`
- `plan` should still be understood as owned by `weavert-devtools`
- `planner` / `coordinator` / `worker` are now owned by `weavert-planning`

The runtime writes the current selected-package and built-in ownership summary into:

- `weavert.services.metadata["first_party_package_catalog"]`
- `weavert.services.metadata["official_package_catalog_provenance"]`
- `weavert.services.metadata["package_resolution"]`

## 4.5 Package Attachment Contract Changes

After boundary convergence, whether a package is "truly attached to the runtime" no longer depends on directory layout alone; it depends on whether it follows protocol attachment:

- `RuntimePackageManifest`
- dependency-ordered assembly
- `PackageContribution`
- capability registry lookup
- host facet discovery
- lifecycle participant registration

If you previously made the following customizations, migrate them first toward the new contract:

- patch kernel-owned first-party assembler tables
- patch optional built-in loader tables
- add package-specific top-level fields directly onto `RuntimeServices`
- infer optional host-helper existence through ad hoc missing-method checks

The preferred migration path is now:

- built-ins -> package contribution
- package-owned runtime object -> capability registry
- optional host operation -> host facet discovery
- package-owned startup / recovery / session behavior -> lifecycle participant
- local external package selection -> `RuntimeConfig.extra_package_manifests` + `RuntimeConfig.requested_packages` + `package_resolution`

A small number of package-specific `RuntimeServices` fields still remain for now, but they should only be treated as compatibility projections.
That also includes the remaining top-level team helpers / workflow helpers: the canonical discovery path is now capability lookup plus host-facet discovery, and the new runtime-owned primary path should no longer treat those wrappers as the source of truth.

The migration posture for external packages needs to change as well:

- `RuntimeConfig.extra_package_manifests` now handles local candidate admission only; it no longer implies that the package enters the active runtime automatically
- admitted external manifests enter the local package catalog first; the graph that truly enters assembly is resolved deterministically from selected first-party manifests, `RuntimeConfig.requested_packages`, and bounded dependency constraints
- duplicate external package names, missing dependencies, conflicting constraints, incompatible candidates, and cyclic dependencies are all structured resolution-phase outcomes instead of hidden registration side effects
- `first_party_package_catalog` is now only the selected official package slice; full official catalog ownership, distribution defaults, and assembly provenance are published separately to `official_package_catalog_provenance`
- `resolved_active_package_graph_provenance` now publishes the current runtime active graph's resolved order, source provenance, and assembly entrypoint separately
- `package_resolution` metadata is published separately from `package_registration`, `package_manifests`, `package_lookup`, and `core_protocol_catalog`; raw candidate inventory and the active resolved graph no longer share one manifest view
- this change still explicitly does not introduce remote discovery, package install, publish workflows, or Python environment package management

The new staged exit criteria should also be made explicit:

- `SESSION_OPEN` replay now triggers only through lifecycle participants rather than a controller special case
- post-ingress acknowledgement now runs only through ingress `completion_receipts` rather than a metadata-key plus controller-branch path
- runtime-owned workflow helpers now look up capabilities / host facets first and only treat older helpers as projections
- `TaskManager` materializes only on demand inside the compatibility facade, not as the default state owner of the runtime-owned primary path
- package-owned host egress has been unified onto `HostRuntime.emit_extension_event()` and delivered through a namespace-aware `HostExtensionEvent` envelope

The canonical lookup keys and wrapper status that matter most in the current repository can be checked directly as follows:

- canonical capability keys
  - `weavert.team.control_plane`
  - `weavert.team.message_bus`
  - `weavert.team.workflows`
- canonical host facet key
  - `weavert.team.workflows`
- host facet authority semantics
  - team workflow list / respond still requires explicit `team_id` or `session_id` scope
  - missing scope or mismatched scope should return scoped failure rather than widening out to a global team view
- canonical extension event contract
  - `HostRuntime.emit_extension_event()`
  - `weavert.hosts.HostExtensionEvent`
  - namespace: `weavert.team`
- canonical control-plane services
  - `RuntimeServices.job_service`
  - `RuntimeServices.task_list_service`
- retained compatibility-only wrappers
  - `TaskManager`
  - `RuntimeServices.teammates`
  - `RuntimeAssembly.teammates`

The replacement matrix for removed team-bridge surfaces is published at:

- `weavert.services.metadata["migration"]["team_protocol_only"]["replacement_matrix"]`
- `weavert.metadata["migration"]["team_protocol_only"]["replacement_matrix"]`

This information is now also written directly into:

- `weavert.services.metadata["core_protocol_catalog"]`
- `weavert.metadata["core_protocol_catalog"]`
- `weavert.services.metadata["official_package_catalog_provenance"]`
- `weavert.metadata["official_package_catalog_provenance"]`
- `weavert.services.metadata["resolved_active_package_graph_provenance"]`
- `weavert.metadata["resolved_active_package_graph_provenance"]`
- `weavert.services.metadata["package_resolution"]`
- `weavert.metadata["package_resolution"]`
- `weavert.services.metadata["package_lookup"]`
- `weavert.metadata["package_lookup"]`
- `weavert.services.metadata["package_service_protocols"]`
- `weavert.metadata["package_service_protocols"]`
- `weavert.services.metadata["compatibility_surfaces"]`
- `weavert.services.metadata["compatibility_boundaries"]`
- `weavert.services.metadata["protocol_only_conformance"]`

During migration, you can read the layers like this:

- `core_protocol_catalog`
  - stable core protocol source of truth
  - covers only `TranscriptStore`, `JobService`, `TaskListService`, `PermissionService`, `ElicitationService`, context contributors, invocation providers, and `HostRuntime`
- `package_resolution`
  - source of truth for the local package catalog, resolution requests, resolved graph, and structured diagnostics
- `official_package_catalog_provenance`
  - source of truth for the manifest-backed official first-party catalog, distribution defaults, assembly-entrypoint provenance, and retired kernel helpers
- `resolved_active_package_graph_provenance`
  - source of truth for the current runtime resolved active graph, package source provenance, and assembly entrypoint
- `package_lookup`
  - source of truth for package-specific canonical capability keys, host-facet keys, service-family protocol keys, and wrapper exit criteria
- `package_service_protocols`
  - source of truth for the canonical keys, resolvers, owners, and compatibility-projection metadata of privileged memory / compaction / isolation bindings
- `compatibility_surfaces`
  - source of truth for retained compatibility helpers / projections
- `compatibility_boundaries`
  - source of truth for the remaining whitelist / exit criteria around raw `runtime_context` and `TaskManager`
- `protocol_only_conformance`
  - source of truth for privileged-service-slot, context-authority, task-authority, provider-provenance, team-bridge, and kernel-assembly findings
  - also publishes the shared finding schema, rule-source mapping, and terminal gate status; embedders / CI can read the same aggregated summary through `RuntimeAssembly.query_assembly_view()`

This means `weavert.team.control_plane`, `weavert.team.workflows`, and `TaskManager` still matter, but they are not part of the stable core protocol catalog itself. The canonical package path continues to be published through capability / host-facet / migration metadata, while removed team-bridge surfaces are no longer written into `compatibility_surfaces`.

Likewise, the package-owned privileged service families for memory, compaction, and isolation should migrate using the same framing:

- canonical metadata key
  - `weavert.services.metadata["package_lookup"]["canonical_service_family_protocols"]`
- canonical resolver
  - `RuntimeServices.resolve_memory_service()`
  - `RuntimeServices.resolve_compaction_service()`
  - `RuntimeServices.resolve_isolation_service()`
- detailed ownership / projection metadata
  - `weavert.services.metadata["package_service_protocols"]`
- compatibility-only projection
  - `RuntimeServices.memory`
  - `RuntimeServices.compaction`
  - `RuntimeServices.isolation`

## 4.6 Closure report, legacy mode, and the final replacement matrix

After this convergence work, migration no longer depends only on scattered notes.
You can now read the closure state published by the runtime directly:

- `weavert.query_closure_report()`
- `weavert.query_compatibility_retirement()`
- `weavert.query_persistence_profile()`
- `weavert.query_isolation_readiness()`

The most practical layer is `compatibility_retirement`.
It tells you:

- which family is already retired
- which family is only tolerated under legacy mode
- what the migration target is for each family

If you only want to answer "what replaces this old surface?", use the table below directly:

| Former surface / family | Current status | canonical replacement |
| --- | --- | --- |
| `TaskManager` | compatibility-only / retired-by-default | `RuntimeServices.job_service` + `RuntimeServices.task_list_service` |
| shared `runtime_context` authoritative write | legacy-mode-only | `PromptContextEnvelope` + `RuntimePrivateContext` |
| `RuntimeServices.memory.collect()` / `hooks.collect()` / `task_discipline.collect()` | compatibility-only | `PackageContribution.context_contributors` |
| `RuntimeServices.memory` | compatibility-only projection | `RuntimeServices.resolve_memory_service()` |
| `RuntimeServices.compaction` | compatibility-only projection | `RuntimeServices.resolve_compaction_service()` |
| `RuntimeServices.isolation` | compatibility-only projection | `RuntimeServices.resolve_isolation_service()` |
| `RuntimeServices.teammates` / `RuntimeAssembly.teammates` | compatibility-only projection | `RuntimeAssembly.resolve_capability(RuntimeCapabilityKey.TEAMMATES.value)` |
| agent-owned `AgentDefinition.hooks` | legacy-mode-only / rejected-by-default | runtime config / host / session API / skill hooks |

The same `closure_report` also publishes persistence and isolation state together:

- the durability difference between the lightweight profile and the production-oriented profile
- whether `worktree` or `remote` isolation is currently `ready`, `not_configured`, or `not_available`

The recommended migration order is:

1. read `closure_report` first
2. then read `compatibility_boundaries` and `package_service_protocols`
3. only then decide whether a legacy family really needs to be enabled explicitly

## 4.7 Explicit Non-Goals

This boundary convergence is explicitly not the following:

- a purity-driven microkernel rewrite
- a flag-day removal of `TaskManager`
- an immediate split of the repository into a physical multi-distribution or multi-wheel packaging layout

The migration framing should be understood like this:

- first freeze new kernel-specific package special cases
- first move the most expensive boundary leaks onto manifest, contribution, or lookup seams
- keep `JobService` as the authoritative surface
- keep treating `TaskManager` as a compatibility facade
- leave any physical package split for a later phase when boundaries and public contracts are more stable

## 4.8 Invocation Provider Package Migration

`RuntimeConfig.extra_invocation_providers` is no longer a canonical assembly input.
If you previously registered a custom provider like this:

```python
weavert = assemble_runtime(
    RuntimeConfig(
        extra_invocation_providers=[repo_provider],
    )
)
```

You should now convert that directly into a provider-only runtime package:

```python
from weavert.package_system.protocols import build_provider_only_invocation_package_manifest

provider_manifest = build_provider_only_invocation_package_manifest(
    name="weavert-provider-only",
    provider_name="repo-commands",
    provider=repo_provider,
)

weavert = assemble_runtime(
    RuntimeConfig(
        extra_package_manifests=(provider_manifest,),
        requested_packages={"weavert-provider-only"},
    )
)
```

The migration guidance is:

- a provider-only package is still an ordinary runtime package, not a new manifest taxonomy
- the default minimal shape is role=`provider` plus dependency=`weavert-core` plus `PackageContribution.invocation_providers`
- provider registration order stays fixed as built-in skill baseline -> package contribution; within the package tier, ordering is still stabilized by contribution `order`, package dependency order, and contribution name
- if one package needs multiple providers, go back to the ordinary `PackageContribution(invocation_providers=(...))` form instead of adding another config bypass

## 5. Recommended Upgrade Checklist

- if you depend on workspace tools, switch to `weavert-full` first and then narrow the surface gradually
- if you depend on `plan`, keep treating it as a `weavert-devtools` helper rather than the shared planning contract itself
- if you want to build a shared-plan workflow, enable `weavert-planning` first and then narrow or extend around `task_*`, `job_*`, and your custom agent profile
- if you expose hooks to third parties, prefer committing only to stable phases plus `callback`
- if you customize host, store, or provider behavior, prefer injecting through package-level seams instead of patching `weavert-core`
- if you still use the old team helpers, migrate first via `weavert.services.metadata["migration"]["team_protocol_only"]["replacement_matrix"]` toward the capability, host-facet, or `HostRuntime.emit_extension_event()` paths
- if you need to inspect the current runtime boundary state, start with `weavert.kernel.diagnostics` and `weavert.services.metadata`
