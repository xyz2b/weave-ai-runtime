# WeaveRT Scenario Runtime Pack Architecture

> Documentation note: This file remains a deep-dive reference. Start with `docs/concepts/packages-and-scenario-packs.md`, then use `docs/architecture/package-system.md` and `docs/guides/use-scenario-packs.md` for the primary reading path.

This reference keeps the scenario-pack boundary ledger: ownership, activation contract, profile shape, and app-owned wiring limits.

Primary docs path:

- Package / scenario-pack concepts -> `docs/concepts/packages-and-scenario-packs.md`
- Package system -> `docs/architecture/package-system.md`
- Activation guide -> `docs/guides/use-scenario-packs.md`

Use this page when you need to answer architecture questions such as:

- what a scenario pack owns versus what the app still owns
- how shared packages differ from scenario packs
- which profile families exist in this repository
- what gets activated by package selection versus host binding

## 1. Five-layer mental model

```text
Runtime distribution
  -> coarse first-party baseline

Shared packages
  -> reusable capability bridges such as retrieval, web, browser, local OS, PIM, git

Scenario pack
  -> product-profile defaults, workflow posture, package-level guidance

App-owned wiring
  -> provider routes, stores, selected packages, host binding, final permissions

Host + permission control plane
  -> approval UX, live mediation, audit sinks, deployment policy
```

The important constraint is simple:

- a scenario pack may recommend a profile posture
- a scenario pack may depend on shared packages
- a scenario pack may publish workflow guidance and metadata
- a scenario pack does not become the final host, provider, or permission owner

## 2. Ownership matrix

| Layer | Owns | Should not own |
| --- | --- | --- |
| distribution | coarse baseline such as `weavert-core/default/full` | product-specific host policy |
| shared package | reusable capability families | the full workflow semantics of one product form |
| scenario pack | product-profile defaults and expected workflow posture | final host binding, final provider selection, final permission composition |
| app-owned wiring | selected packages, routes, stores, host binding, deployment policy | reusable low-level bridge implementation |
| host / permission plane | approvals, audit, live mediation | repo-level package catalog design |

In practice:

- shared packages answer "is this capability reusable across product forms?"
- scenario packs answer "what should this product profile look like by default?"
- app wiring answers "what does this deployment actually ship?"

## 3. Distribution, scenario pack, and `.weavert/` stay separate

All three layers remain, because they solve different problems:

| Layer | Primary question |
| --- | --- |
| distribution | which first-party baseline do I start from? |
| scenario pack | what workflow posture should this product profile default to? |
| `.weavert/` | what tools, agents, and skills are specific to this workspace? |

Recommended composition order:

1. Choose a distribution.
2. Add one scenario pack or selected shared packages.
3. Add project-local definitions under `.weavert/`.
4. Let the app bind its own host, provider, store, and policy.

Scenario packs do not replace `.weavert/`, and `.weavert/` does not replace package composition.

## 4. Shared packages versus scenario packs

The repository uses two complementary package shapes:

| Package shape | Good fit | Typical examples in this repo |
| --- | --- | --- |
| shared package | one reusable capability family | retrieval, web, browser, local OS, PIM, git, workspace intelligence |
| scenario pack | one product-profile default | coding, chat, local assistant |

Shared packages should carry reusable bridges or utilities.
Scenario packs should compose those packages into a profile-level default posture.

This is why:

- retrieval should not be buried separately inside every profile
- browser, local OS, and PIM bridges should not be rewritten per assistant flavor
- coding-oriented git or workspace inspection should stay reusable outside one demo app

## 5. Reference profile shapes in this repository

The current reference profiles are:

| Profile | Recommended first-party packages | Typical shared-package dependencies | Primary posture |
| --- | --- | --- | --- |
| coding | `weavert-devtools`, `weavert-planning`, `weavert-builtin-workflows` | `weavert-shared-git`, `weavert-shared-workspace-intelligence` | workspace-oriented, shell-capable, review/verification visible |
| chat | `weavert-memory` | `weavert-shared-retrieval`, `weavert-shared-web-research` | read-mostly, grounded answers, citations, memory-assisted workflows |
| local assistant | `weavert-memory` | `weavert-shared-retrieval`, `weavert-bridge-browser`, `weavert-bridge-local-os`, `weavert-bridge-pim` | host-centric, staged actions, stronger approval and audit expectations |

What each profile contributes conceptually:

- coding
  - coding-oriented workflow roles and skills
  - shared repo-inspection capability
  - a posture where workspace mutation is expected, but still app-mediated
- chat
  - grounded-answer workflow roles and skills
  - retrieval and web grounding composition
  - a posture that does not implicitly inherit coding surfaces
- local assistant
  - host-mediated workflow roles and skills
  - browser / OS / PIM bridge composition
  - a posture where live execution remains host-owned even if staging tools are present

The exact tool, agent, and skill inventory is intentionally not repeated here.
Use assembled runtime inspection or the product-kit READMEs when you need the current concrete surface list.

## 6. Activation contract

Scenario packs do not introduce a new kernel API.
They use the ordinary package-selection contract:

- `RuntimeConfig.distribution`
- `RuntimeConfig.enabled_packages`
- `RuntimeConfig.disabled_packages`
- `RuntimeConfig.extra_package_manifests`
- `RuntimeConfig.requested_packages`

The activation rules that matter most are:

- scenario packs are not part of default distribution baselines
- the runtime does not load them unless the app admits them explicitly
- recommended first-party packages are still app-selected
- requesting only a scenario pack does not magically materialize unrelated first-party tools, agents, or skills

Two useful inspection paths remain authoritative:

- `weavert.services.metadata["package_manifests"]`
  - inspect projected package metadata
- `RuntimeServices.require_capability(...)`
  - inspect the mirrored scenario-pack capability payload

## 7. App-owned wiring remains final authority

Even after a scenario pack is active, the app still owns:

- provider route selection
- transcript, memory, and job store selection
- host binding and host UX
- final permission composition
- browser / OS / PIM live execution adapters
- deployment-specific audit and approval posture

This is especially important for local-assistant shapes:

- package surfaces may stage actions
- package surfaces may declare bridge expectations
- the host still decides whether any real browser, OS, or PIM authority exists

Treat the deployable shape as:

```text
selected first-party packages
+ admitted shared/scenario packages
+ model routes
+ stores
+ host binding
+ final permission policy
= deployable app
```

## 8. Related docs

- `docs/concepts/packages-and-scenario-packs.md`
- `docs/architecture/package-system.md`
- `docs/guides/use-scenario-packs.md`
- `docs/deep-dives/weavert-scenario-runtime-pack-quickstart.md`
- `examples/README.md`
