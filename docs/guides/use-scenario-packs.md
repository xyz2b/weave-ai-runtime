# Use Scenario Packs

## Who is this for?

Users who want a product-profile baseline such as coding, chat, or local assistant without giving up host ownership.

## Prerequisites

- a working runtime baseline
- the relevant product-kit package installed
- a clear idea of which profile you want to compose

## The boundary to remember first

A scenario pack is an ordinary package-selection surface, not a new runtime mode and not your final host owner.
It can recommend posture and publish workflow surfaces, but the app still owns:

- provider routes
- stores
- final permission composition
- host UX and approvals

## Activation path

The canonical pattern is:

1. choose a distribution
2. admit the manifests through `extra_package_manifests`
3. request the package by name through `requested_packages`
4. inspect the assembled runtime posture

Minimal coding example:

```python
from pathlib import Path

from weavert import RuntimeConfig, assemble_runtime
from weavert_kit_coding import coding_scenario_runtime_pack_manifests

config = RuntimeConfig.for_ordinary_workflow(Path.cwd())
config.extra_package_manifests = coding_scenario_runtime_pack_manifests()
config.requested_packages.add("weavert-scenario-coding")
runtime = assemble_runtime(config)
```

## Common profile recipes

### Coding

Use when you want workspace-oriented tooling, planner or reviewer roles, and shared git or workspace-intelligence surfaces.

Import path:

```python
from weavert_kit_coding import coding_scenario_runtime_pack_manifests
```

### Chat

Use when you want retrieval, citations, and response-quality workflows.

Import path:

```python
from weavert_kit_chat import chat_scenario_runtime_pack_manifests
```

### Local assistant

Use when you want a stronger host-centric posture, often alongside browser, local-OS, or PIM bridges.

Import path:

```python
from weavert_kit_local_assistant import local_assistant_scenario_runtime_pack_manifests
```

### Shared packages only

Use this path when you want reusable capability bridges without adopting a full scenario workflow profile.

## What to inspect after activation

After assembly, inspect:

- whether the package is actually active rather than merely admitted
- which workflow agents or skills appeared
- which shared package dependencies were pulled in
- whether package-specific diagnostics warn about missing recommended first-party packages

## Expected result

The scenario pack contributes workflow surfaces and guidance, while the app still owns final host, provider, and permission decisions.

## Next step

Use `../../examples/apps/code_assistant/README.md` when you want to see a richer host-bound sample built on the coding scenario pack.

## See also

- `../concepts/packages-and-scenario-packs.md`
- `../architecture/package-system.md`
- `../deep-dives/weavert-scenario-runtime-pack-quickstart.md`
- `../deep-dives/weavert-scenario-runtime-pack-architecture.md`
