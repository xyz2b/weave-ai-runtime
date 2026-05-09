# WeaveRT Scenario Runtime Pack Quickstart

> Documentation note: This file remains a deep-dive reference. Start with `docs/concepts/packages-and-scenario-packs.md`, then use `docs/guides/use-scenario-packs.md` and `docs/architecture/package-system.md` for the primary reading path.

This reference keeps the scenario-pack activation cheat sheet: one canonical template, profile-selection guidance, activation checks, and the mistakes that most often cause confusion.

Primary docs path:

- Package / scenario-pack concepts -> `docs/concepts/packages-and-scenario-packs.md`
- Activation guide -> `docs/guides/use-scenario-packs.md`
- Package system -> `docs/architecture/package-system.md`

Use this page when you already understand the boundary and just need the shortest package-selection reminder.

## 1. Baseline to remember first

All reference shared and scenario packages follow the same rules:

- they are not part of the default distribution baseline
- they do not enter the runtime automatically
- they must be admitted through `RuntimeConfig.extra_package_manifests`
- they become active only when requested through `RuntimeConfig.requested_packages`

So the mental model is:

1. choose `distribution`
2. choose any first-party `enabled_packages`
3. admit and request external or optional packages
4. let the app own provider, store, host, and final permission policy

## 2. One canonical activation template

```python
from pathlib import Path

from weavert.runtime_kernel import RuntimeConfig, assemble_runtime
from weavert_kit_coding import coding_scenario_runtime_pack_manifests

runtime = assemble_runtime(
    RuntimeConfig(
        working_directory=Path.cwd(),
        distribution="weavert-core",
        enabled_packages=set(),
        extra_package_manifests=coding_scenario_runtime_pack_manifests(),
        requested_packages={"weavert-scenario-coding"},
    )
)
```

For other profiles, the shape stays the same.
You mainly swap:

- the manifest provider import
- `enabled_packages`
- `requested_packages`

## 3. Profile selection matrix

| Profile | Manifest helper | Request | Recommended first-party packages | Primary posture |
| --- | --- | --- | --- | --- |
| coding | `coding_scenario_runtime_pack_manifests()` | `weavert-scenario-coding` | `weavert-devtools`, `weavert-planning`, `weavert-builtin-workflows` | workspace-oriented, review and verification visible |
| chat | `chat_scenario_runtime_pack_manifests()` | `weavert-scenario-chat` | `weavert-memory` | grounded answers, read-mostly default |
| local assistant | `local_assistant_scenario_runtime_pack_manifests()` | `weavert-scenario-local-assistant` | `weavert-memory` | host-centric, staged bridges, stronger approval posture |
| shared packages only | package-specific reference manifest helpers | shared package names only | none by default | capability augmentation without a full scenario workflow |

Practical notes:

- coding is the closest fit for repo-oriented assistants
- chat keeps coding-oriented mutation surfaces out by default
- local assistant still depends on host-bound bridge facets for live browser, OS, or PIM behavior
- shared-packages-only is the right path when you already have your own shell or main agent

## 4. What each profile really gives you

Think in terms of posture, not in terms of memorizing every tool name:

- coding
  - coding-oriented shared packages plus workflow roles and verification loops
- chat
  - retrieval, citations, and chat-oriented workflow roles
- local assistant
  - bridge-heavy, host-mediated workflow posture
- shared packages only
  - reusable capability slices without the higher-level scenario workflow layer

If you need the exact assembled capability list, inspect the runtime after activation rather than relying on a static document ledger.

## 5. How to confirm a package really entered the runtime

Start with two inspection paths:

- projected manifest metadata
  - `runtime.services.metadata["package_manifests"]`
- capability payload
  - `runtime.services.require_capability(...)`

Use them to confirm:

- the package candidate was admitted
- the package was actually selected into the resolved graph
- the expected profile metadata or capability payload is present

## 6. Local-assistant bridge warning

The most common misunderstanding is around local-assistant bridges.

Those packages may provide:

- staged bridge tools
- bridge expectations
- host-facing capability contracts

They do not automatically provide:

- live browser authority
- live OS authority
- live PIM authority

Those remain app- or host-owned bindings.

## 7. Common mistakes

- admitting a manifest without requesting the package
- requesting a scenario pack without enabling its recommended first-party packages
- assuming a scenario pack is a new runtime mode rather than ordinary package selection
- assuming local-assistant bridge packages secretly take over browser, OS, or PIM execution
- treating shared packages and scenario packs as the same abstraction

## 8. What to read next

- architecture boundary -> `docs/deep-dives/weavert-scenario-runtime-pack-architecture.md`
- primary user guide -> `docs/guides/use-scenario-packs.md`
- package-surface and extension choices -> `docs/deep-dives/weavert-user-extension-guide.md`
- fuller app sample -> `examples/apps/code_assistant/app.py`
