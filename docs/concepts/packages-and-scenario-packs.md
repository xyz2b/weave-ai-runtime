# Packages and Scenario Packs

Packages are how WeaveRT composes reusable runtime capability beyond one local project directory.

## Who is this for?

- Adopters who already know the landing-page story and now need the core runtime vocabulary.

## Prerequisites

- Read `../introduction/what-is-weavert.md` first.
- Skim `../getting-started/quickstart.md` if you want the terminology anchored in a runnable path.

## The five-layer mental model

```text
Runtime distribution
  -> first-party baseline selection

Shared packages
  -> reusable capability surfaces such as retrieval, web, git, or browser bridges

Scenario packs
  -> product-profile guidance and workflow surfaces

App-owned wiring
  -> provider routes, stores, host binding, final package requests

Host and permission plane
  -> deployment-specific approvals, UX, and audit posture
```

This model matters because it prevents one package from silently becoming your whole product.

## First-party package roles

The current package family is split by responsibility:

- core runtime: `weavert`
- framework packs
  - capability: `weavert-memory`, `weavert-team`
  - mechanism: `weavert-compaction`, `weavert-isolation`
  - integration: `weavert-openai`, `weavert-hosts-reference`, `weavert-stores-file`
  - workflow: `weavert-planning`, `weavert-devtools`, `weavert-builtin-workflows`
- product kits: coding, chat, local assistant, plus shared common kits
- toolchain: starter and testing helpers

See `../../packages/README.md` and `../../packages/framework-packs/README.md` for the workspace view.

## Shared packages

Shared packages contribute reusable capability that more than one product shape can use.
Examples include:

- retrieval
- web grounding
- git inspection
- workspace intelligence
- browser or local OS bridges

Shared packages answer "is this capability reusable across products?"

## Quick boundary check for the easy-to-confuse ones

- retrieval decides which grounding items or memory passages are most relevant and prepares citations
- web grounding searches public websites and fetches remote text in a read-only posture
- browser bridges work through an app-owned browser for state, navigation, and interaction
- local-OS bridges expose generic machine surfaces such as files, clipboard, notifications, and processes
- PIM bridges expose structured personal-data surfaces such as calendars, contacts, reminders, and tasks

## Scenario packs

Scenario packs are product-profile packages.
They answer "what should this product shape feel like by default?"

A scenario pack can:

- recommend a baseline tool and workflow posture
- publish workflow-focused agents and skills
- depend on shared packages
- contribute package-level guidance and diagnostics

A scenario pack should not:

- own the final host integration
- own the final permission policy
- own provider or store authority for the whole app
- replace your workspace-local `.weavert/` authoring layer

## Packages, scenario packs, and `.weavert/` are different things

Keep these three layers separate:

- distribution
  - coarse-grained first-party baseline such as `weavert-core`, `weavert-default`, or `weavert-full`
- scenario pack
  - product-profile package such as coding, chat, or local assistant
- `.weavert/`
  - workspace-local tools, agents, and skills for one project

A typical stack is:

1. choose a distribution
2. request a scenario pack and any shared packages you need
3. add project-local behavior under `.weavert/`
4. bind your own host and final permission posture

## A useful metadata distinction

Package-facing documentation is easier to reason about if you keep three categories apart:

- runtime-resolved
  - facts the runtime determines, such as whether a package is admitted or active
- runtime-projected
  - facts the runtime exposes from a package for inspection
- convention-only
  - vocabulary used by a package family to describe itself to callers

This is why a scenario pack can publish profile guidance without becoming the host owner.

## Activation model

Package admission and activation are explicit.
A common pattern is:

- provide manifests through `extra_package_manifests`
- request the package by name through `requested_packages`
- inspect the assembled runtime posture

This keeps composition visible instead of magical.

## Common profile paths

- coding
  - workspace-oriented tools, review loops, git and workspace-intelligence shared surfaces
- chat
  - retrieval, citation, and response-quality workflow surfaces
- local assistant
  - stronger host and approval posture, often with browser or local-OS shared bridges
- shared-packages only
  - when you want reusable bridges without adopting a full scenario workflow profile

## Next step

- Use `../guides/use-scenario-packs.md` when you are ready to activate a profile or shared package set.
- Read `../architecture/package-system.md` for the deeper activation and ownership model.

## See also

- `../guides/use-scenario-packs.md`
- `../architecture/package-system.md`
- `../deep-dives/weavert-scenario-runtime-pack-architecture.md`
