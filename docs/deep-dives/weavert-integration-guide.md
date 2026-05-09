# WeaveRT Integration Guide

> Documentation note: This file remains a deep-dive reference. Start with `docs/getting-started/quickstart.md`, then use `docs/guides/bind-a-host.md`, `docs/guides/integrate-openai.md`, and `docs/architecture/overview.md` for the primary reading path.

This reference keeps the integration ledger: stable outer surfaces, package attachment boundaries, runtime flow, and the ownership rules that matter when embedding WeaveRT into a larger system.

Primary docs path:

- First run -> `docs/getting-started/quickstart.md`
- Official starter path -> `docs/getting-started/starter-scaffolds.md`
- Host binding -> `docs/guides/bind-a-host.md`
- OpenAI live route -> `docs/guides/integrate-openai.md`
- Architecture overview -> `docs/architecture/overview.md`

Use this page when you need to answer questions such as:

- which runtime surface a caller should integrate with first
- how `RuntimeConfig`, `RuntimeAssembly`, `BoundHostRuntime`, and `DefinitionSourcePaths` divide responsibility
- what "package boundary" means in runtime terms
- which lifecycle and policy concerns remain app-owned

## 1. One-sentence mental model

WeaveRT is a composable AI runtime backplane, not a preset prompt-owned assistant app.

Most integrators should stop at four outer surfaces:

- `RuntimeConfig`
- `RuntimeAssembly`
- `BoundHostRuntime`
- `DefinitionSourcePaths`

Those surfaces sit outside the kernel-owned session and turn loop:

```text
your app / host
  -> RuntimeConfig
  -> RuntimeAssembly
  -> BoundHostRuntime
  -> DefinitionSourcePaths
  -> runtime-owned session / turn / recovery / memory / host mediation
```

## 2. Stable integration surfaces

### 2.1 `RuntimeConfig`

`RuntimeConfig` is the top-level assembly surface.
It owns the desired runtime posture:

- distribution selection
- working directory
- discovery sources
- built-in selection and replacement
- package admission and package requests
- host binding inputs
- model client and model routes
- transcript and child-run stores
- memory config
- teammate orchestration and related policy inputs

Common entry paths:

- manual `RuntimeConfig(...)`
- `RuntimeConfig.for_ordinary_workflow(project_root)`
- `RuntimeConfig.for_headless_live(project_root)`
- `RuntimeConfig.for_host_bound(project_root)`

Practical rule:

- choose a preset when you want a known assembly posture fast
- construct manually when your integration already has strong custom routing, stores, or package policy

### 2.2 `RuntimeAssembly`

`RuntimeAssembly` is the public runtime entrypoint after assembly.
This is where most business callers should attach.

It owns:

- one-shot prompt helpers
- streaming prompt helpers
- session creation
- invocation visibility and diagnostics
- assembly-level inspection and metadata access

If your goal is "embed the runtime into my service and run workflows," `RuntimeAssembly` is usually enough.

### 2.3 `BoundHostRuntime`

Use `RuntimeAssembly.bind_host(host)` when your integration is a real host rather than a simple caller.

This is the right boundary for:

- CLI shells
- SDK-owned interactive sessions
- web or desktop UI shells
- approvals, elicitation, notifications, and turn-event rendering

The host owns presentation and interaction.
The runtime still owns session, turn, and orchestration semantics.

### 2.4 `DefinitionSourcePaths`

`DefinitionSourcePaths` is the capability-delivery seam for local tools, agents, and skills.

Default discovery rules remain:

- `tools/*.py`
- `agents/*.md`
- `skills/**/SKILL.md`

Treat this as the supported local extension path.
Do not treat it as permission to patch kernel internals or built-in assembler tables.

## 3. Distribution and package boundaries

Three layers are easy to confuse:

| Layer | Owns |
| --- | --- |
| distribution | coarse first-party baseline |
| external or optional packages | admitted reusable capability or workflow surfaces |
| app-owned wiring | final provider, store, host, and permission choices |

Important rules:

- distribution changes which first-party packages are assembled by default
- external packages enter through `extra_package_manifests`
- admitted packages become active only when actually selected into the resolved graph
- scenario packs are ordinary packages, not a separate kernel mode

For coding, chat, or local-assistant profiles, the useful mental split is:

- distribution
  - coarse first-party baseline
- scenario pack
  - product-profile guidance through ordinary package selection
- app-owned wiring
  - provider routes, stores, host binding, final permissions

This is why a scenario pack must not be treated as the final host or permission owner.

## 4. Package boundary means protocol attachment

In WeaveRT, a package is not important merely because code moved into a different directory.
A package matters when it attaches behavior through stable runtime protocols such as:

- manifest admission and dependency ordering
- `PackageContribution`
- invocation providers
- context contributors
- capability lookup
- host-facet lookup
- lifecycle participation

Preferred extension order:

1. local tool / agent / skill definitions
2. stable public hooks
3. package contribution
4. capability lookup
5. host-facet discovery

Avoid treating these as the primary extension story:

- patching kernel-owned first-party tables
- adding package-specific ad hoc fields to `RuntimeServices`
- extending mandatory host contracts for one package family

## 5. Who should attach where

| Integrator role | Preferred surface |
| --- | --- |
| business caller | `RuntimeAssembly` |
| CLI / SDK / UI host | `BoundHostRuntime` |
| local capability author | `DefinitionSourcePaths` |
| platform integrator | `RuntimeConfig` plus model, memory, package, and store policy |
| runtime maintainer | session or turn internals |

Practical rule:

- business caller: start from `RuntimeAssembly`
- host integrator: start from `bind_host(...)`
- capability author: start from `.weavert/` discovery and guides
- only runtime maintainers should begin at `SessionController` or `TurnEngine`

## 6. Three integration postures

### 6.1 Embeddable runtime

Use this posture when your product mainly needs:

- prompt execution
- session reuse
- offline or headless workflows
- minimal control-plane customization

Primary surface:

- `RuntimeAssembly`

### 6.2 Host-bound runtime

Use this posture when your product needs:

- explicit lifecycle ownership
- approval and elicitation UX
- notifications and turn events
- host-local shell or UI behavior

Primary surface:

- `BoundHostRuntime`

### 6.3 Capability-extending runtime

Use this posture when your product needs:

- local tools, agents, or skills
- package-level reusable capability groups
- custom invocation providers
- scenario-pack or shared-package composition

Primary surfaces:

- `DefinitionSourcePaths`
- package manifests and package contributions

## 7. Request-flow boundary that integrators should remember

One request still follows the same owned flow:

```text
input
  -> ingress normalization
  -> session decides whether to admit a turn
  -> active context assembly
  -> model attempt
  -> tools / skills / agents / recovery
  -> terminal turn result
  -> transcript and durable artifact updates
```

The important integration consequence is:

- not every input becomes a turn
- active context is a projection, not the whole runtime-private state bag
- one model attempt finishing does not necessarily mean the turn is terminal
- recovery, tool continuation, permissions, and host mediation remain runtime-owned control flow

## 8. Extension points worth preserving at the platform layer

The most valuable long-lived platform seams are:

### 8.1 Model routes

Keep model routing at the platform layer when:

- different workflows need different providers or policies
- you want route-level request shaping
- you need provider-specific behavior isolated from application prompts

### 8.2 Memory policy

Keep memory policy at the platform layer when:

- retrieval versus extraction tradeoffs should be configurable
- different deployments need different persistence or compaction posture
- memory should remain a runtime service rather than one prompt convention

### 8.3 Provider-only invocation packages

Use package attachment when a capability is really a provider or integration concern rather than a single local tool definition.

### 8.4 Request-time context contributors

Use contributors when package-owned logic must add:

- prompt-visible fragments
- runtime-private fragments
- diagnostics

Do not confuse this with HookBus event processing.

### 8.5 Runtime-owned team mode

Treat team or teammate orchestration as runtime-owned coordination, not host-owned orchestration.
The host may observe or render team activity, but it should not become the authoritative owner of team state merely because it renders the events.

## 9. What to inspect when integration goes wrong

If an integration misbehaves, inspect the layer that actually owns the problem:

- assembly posture
  - `RuntimeConfig`
  - assembly metadata
- capability visibility
  - invocation diagnostics
  - package selection and package manifests
- host binding
  - host lifecycle
  - permission and elicitation wiring
- runtime flow
  - ingress versus turn admission
  - recovery versus terminal turn outcome

This is usually more productive than starting inside the turn engine.

## 10. Short integration checklist

1. Pick the right outer surface first.
2. Keep package admission separate from package activation.
3. Keep scenario-pack ownership separate from final app-owned wiring.
4. Keep host presentation separate from runtime orchestration authority.
5. Extend through definitions, packages, routes, memory policy, and hooks before touching kernel internals.

## 11. Related docs

- `docs/architecture/overview.md`
- `docs/architecture/request-lifecycle.md`
- `docs/guides/bind-a-host.md`
- `docs/guides/integrate-openai.md`
- `docs/deep-dives/weavert-definition-authoring-guide.md`
- `docs/deep-dives/weavert-control-plane-extension-guide.md`
- `docs/deep-dives/current-system-architecture.md`
- `docs/deep-dives/layered-memory-weavert-v2.md`
