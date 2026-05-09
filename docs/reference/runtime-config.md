# RuntimeConfig Reference

`RuntimeConfig` is the main assembly surface for ordinary framework users.

## Who is this for?

- Readers who already know the workflow and now need a stable lookup page.

## Prerequisites

- Read the matching guide or concept page first.
- Treat this page as a reference sheet, not the first-stop tutorial.

## Most-used presets

- `RuntimeConfig.for_ordinary_workflow(project_root)`
  - ordinary project-local workflow baseline
- `RuntimeConfig.for_headless_live(project_root)`
  - live route baseline with preflight-friendly posture
- `RuntimeConfig.for_host_bound(project_root)`
  - host-oriented baseline for CLI, SDK, or UI-owned integrations

## Common decisions carried by `RuntimeConfig`

The most important slots usually fall into these groups:

- distribution and package posture
  - `distribution`
  - `enabled_packages` / `disabled_packages`
  - `extra_package_manifests`
  - `requested_packages`
- working roots and discovery
  - `working_directory`
  - discovery sources such as user and project `.weavert/`
- model layer
  - `model_client`
  - model providers and routes
- control-plane and persistence layer
  - host bindings
  - transcript and child-run stores
  - memory configuration

## Good default posture

Start with a preset whenever possible.
Add only the extra controls you actually need.

## When to move beyond the preset

Reach for manual `RuntimeConfig(...)` construction when you need:

- non-default package selection
- custom transcript or child-run stores
- custom model route wiring
- explicit host-oriented integration

If you do want a host-oriented baseline without hand-building everything, start from `RuntimeConfig.for_host_bound(...)` first and then override only what the host needs.

For memory behavior, distinguish two cases:

- use `RuntimeConfig.memory_config` when you want declarative tuning
- if you truly need a different memory backend, that replacement is deeper than `RuntimeConfig` today because there is no direct `RuntimeConfig.memory_provider` slot

## Next step

- Return to `../guides/build-your-first-project.md` if you still want the preset-first adoption path.
- Use `../guides/integrate-openai.md` when the next change is a live route or provider configuration.
- Read `../architecture/package-system.md` if you are adjusting package admission or activation behavior.

## See also

- `../concepts/runtime-model.md`
- `../guides/build-your-first-project.md`
- `../guides/integrate-openai.md`
- `../architecture/package-system.md`
- `../getting-started/quickstart.md`
- `../deep-dives/weavert-integration-guide.md`
