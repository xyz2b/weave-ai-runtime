# Public Package Catalog

This page describes the public first-party package surface for WeaveRT.
Use it when you need one place that answers three questions:

- what each published package is for
- how the package is normally used
- how install names, import roots, and runtime activation names relate

## Who is this for?

- users choosing published packages from PyPI or TestPyPI
- maintainers who need one public-facing inventory of the supported package surface
- adopters deciding whether they need a baseline bundle, a framework pack, a scenario kit, or only a shared bridge kit

## Read this catalog in layers

The public package surface has four layers:

1. baseline runtime and toolchain packages
2. framework packs that extend the runtime directly
3. shared product-kit packages that expose lower-layer bridges
4. scenario kits that publish higher-layer product-profile defaults

Toolchain packages are never runtime activation targets.
Scenario kits and shared kits use package manifests plus `requested_packages`; their public install names are not the same as their runtime activation names.

## Quick install entrypoints

Use these as the default published install paths:

- starter-first adoption path:

```bash
python -m pip install weavert-starter weavert-testing
```

- full runtime baseline without scaffolding:

```bash
python -m pip install weavert-full
```

- narrow custom runtime starting from the kernel only:

```bash
python -m pip install weavert
```

## Runtime baselines and toolchain

| Install name | Import root | Runtime activation | What it gives you | Use when |
| --- | --- | --- | --- | --- |
| `weavert` | `weavert` | none | Core runtime kernel, assembly APIs, definition discovery, and extension seams | You want the smallest custom starting point and will choose add-ons yourself |
| `weavert-full` | none | none | Installable full first-party baseline that matches `RuntimeConfig.for_ordinary_workflow(...)` | You want the standard first-party runtime surface without using the starter CLI |
| `weavert-starter` | `weavert_starter` | none | Official starter scaffolds and the `weavert-starter` CLI | You want the fastest project bootstrap path |
| `weavert-testing` | `weavert_testing` | none | Deterministic testing harness, scripted model support, fixtures, and assertions | You want offline validation or regression tests for a WeaveRT app |

## Framework packs

These are direct first-party runtime add-ons.
`weavert-full` already installs the common baseline set below.
Install them separately only when you are narrowing or customizing the surface instead of taking the full baseline.

| Install name | Import root | Role | What it adds | Typical use |
| --- | --- | --- | --- | --- |
| `weavert-memory` | `weavert_memory` | Capability | Layered memory runtime support and memory-specific services | Add durable or session memory behavior to a custom runtime |
| `weavert-team` | `weavert_team` | Capability | Team control and teammate orchestration surfaces | Add multi-agent or teammate-style coordination |
| `weavert-compaction` | `weavert_compaction` | Mechanism | Compaction strategies and manager support | Reduce context pressure in longer workflows |
| `weavert-isolation` | `weavert_isolation` | Mechanism | Isolation adapters and scoped execution boundaries | Separate tool or host work behind explicit isolation seams |
| `weavert-openai` | `weavert_openai` | Integration | First-party OpenAI provider binding and route surfaces | Use live OpenAI model routes |
| `weavert-hosts-reference` | `weavert_hosts_reference` | Integration | Reference CLI and SDK host implementations | Start from reusable host examples instead of building the host shell from zero |
| `weavert-stores-file` | `weavert_stores_file` | Integration | File-backed transcript and runtime stores | Use local durable state, transcript capture, or file-backed testing |
| `weavert-builtin-workflows` | `weavert_builtin_workflows` | Workflow | Reusable first-party workflow skills | Reuse shared workflow behavior below scenario-pack ownership |
| `weavert-planning` | `weavert_planning` | Workflow | Planning agents plus coordinator-style planning support | Add planner, coordinator, or task-list style workflow surfaces |
| `weavert-devtools` | `weavert_devtools` | Workflow | Workspace and coding built-ins | Add developer-oriented workflow helpers and coding surfaces |

## Shared product-kit packages

These are lower-layer building blocks.
Use them when you want one reusable bridge or shared capability without taking a full scenario profile.

| Install name | Import root | Runtime activation | What it adds | Typical use |
| --- | --- | --- | --- | --- |
| `weavert-kit-common-retrieval` | `weavert_kit_common_retrieval` | `weavert-shared-retrieval` | Shared retrieval surfaces | Reuse retrieval support across chat or assistant products |
| `weavert-kit-common-web-research` | `weavert_kit_common_web_research` | `weavert-shared-web-research` | Unified read-only web research surfaces with `web_research`, profile facets, provider metadata, freshness outcomes, single-page `web_fetch`, and low-level `web_*` primitives | Add web information retrieval without taking a full scenario profile |
| `weavert-kit-common-git` | `weavert_kit_common_git` | `weavert-shared-git` | Shared git inspection surfaces | Add repository inspection to a custom coding workflow |
| `weavert-kit-common-workspace-intelligence` | `weavert_kit_common_workspace_intelligence` | `weavert-shared-workspace-intelligence` | Shared workspace-intelligence surfaces | Add workspace-aware coding support |
| `weavert-kit-common-browser` | `weavert_kit_common_browser` | `weavert-bridge-browser` | Shared browser bridge surfaces | Add browser-side interaction to a host-centric assistant |
| `weavert-kit-common-local-os` | `weavert_kit_common_local_os` | `weavert-bridge-local-os` | Shared local-OS bridge surfaces | Add local machine bridge behavior without taking a full scenario pack |
| `weavert-kit-common-pim` | `weavert_kit_common_pim` | `weavert-bridge-pim` | Shared PIM bridge surfaces | Add calendar, notes, or personal-information-management style bridges |

## Commonly confused shared kits

- `weavert-kit-common-retrieval` ranks, excerpts, and prepares citations from grounding items you already have, such as notes, memory, or fetched passages. It does not search the public web and it does not drive a browser.
- `weavert-kit-common-web-research` owns the recommended `web_research` entrypoint for chat, coding, local-assistant, and other profile-driven public-web research. Use `profile` to select strategy; profile-specific fields appear under `facets.<profile>`.
- `weavert-kit-common-web-research` performs read-only public-web search, single-page page fetch, page-local evidence finding, and multi-page inspection behind `web_research`. It does not expose browser navigation, clicks, public batch-fetch fields, or host-side browser control.
- `weavert-kit-common-browser` is a host-mediated browser bridge for browser state, navigation, and interaction. It is not a web-search adapter and it does not imply autonomous browser ownership.
- `weavert-kit-common-local-os` bridges generic local-machine surfaces such as files, clipboard, notifications, and processes. It is broader device plumbing, not structured personal-data tooling.
- `weavert-kit-common-pim` bridges structured personal-information surfaces such as calendar events, contacts, reminders, and tasks. Use it for PIM objects, not generic local-OS access.

## Scenario kits

These are higher-layer product-profile entrypoints.
They still do not own your final host, provider routes, or permission posture.
They publish a package-selection baseline that your app composes explicitly.

| Install name | Import root | Runtime activation | What it adds | Composes |
| --- | --- | --- | --- | --- |
| `weavert-kit-chat` | `weavert_kit_chat` | `weavert-scenario-chat` | Chat-oriented product-profile defaults | retrieval + web |
| `weavert-kit-coding` | `weavert_kit_coding` | `weavert-scenario-coding` | Coding-oriented product-profile defaults | git + workspace intelligence |
| `weavert-kit-local-assistant` | `weavert_kit_local_assistant` | `weavert-scenario-local-assistant` | Host-centric local-assistant profile defaults | retrieval + browser + local-OS + PIM |

## How to use scenario kits

Installing a scenario kit is not enough by itself.
You still need to admit its manifests and request its runtime activation name.

Example:

```python
from pathlib import Path

from weavert import RuntimeConfig, assemble_runtime
from weavert_kit_coding import coding_scenario_runtime_pack_manifests

config = RuntimeConfig.for_ordinary_workflow(Path.cwd())
config.extra_package_manifests = coding_scenario_runtime_pack_manifests()
config.requested_packages.add("weavert-scenario-coding")
runtime = assemble_runtime(config)
```

## How to use shared product-kit packages

Shared kits follow the same pattern, but with their lower-layer activation names.

Example:

```python
from pathlib import Path

from weavert import RuntimeConfig, assemble_runtime
from weavert_kit_common_git import reference_shared_package_manifests

config = RuntimeConfig.for_ordinary_workflow(Path.cwd())
config.extra_package_manifests = reference_shared_package_manifests()
config.requested_packages.add("weavert-shared-git")
runtime = assemble_runtime(config)
```

For the other shared kits, keep the pattern and swap:

- the import root
- the manifest helper
- the runtime activation name from the table above

## What to read next

- package combinations by scenario: `../guides/choose-package-combinations.md`
- scenario-pack activation details: `../guides/use-scenario-packs.md`
- runtime package-selection model: `../architecture/package-system.md`
- default getting-started install path: `../getting-started/installation.md`
- source-checkout install path: `../getting-started/install-from-source.md`
