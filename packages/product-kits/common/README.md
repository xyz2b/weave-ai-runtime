# Shared Product-Kit Packages

This family groups reusable product-kit packages shared across multiple scenario packs.

## What this family owns

- reusable bridges such as retrieval, web research, git, browser, local-OS, PIM, and workspace intelligence
- shared product-kit packages that stay below scenario-pack ownership

## Concrete packages

| Package root | Install name | Import root | Runtime activation | Exposure tier |
| --- | --- | --- | --- | --- |
| `retrieval/` | `weavert-kit-common-retrieval` | `weavert_kit_common_retrieval` | `weavert-shared-retrieval` | Lower-layer shared kit |
| `web-research/` | `weavert-kit-common-web-research` | `weavert_kit_common_web_research` | `weavert-shared-web-research` | Lower-layer shared kit |
| `git/` | `weavert-kit-common-git` | `weavert_kit_common_git` | `weavert-shared-git` | Lower-layer shared kit |
| `workspace-intelligence/` | `weavert-kit-common-workspace-intelligence` | `weavert_kit_common_workspace_intelligence` | `weavert-shared-workspace-intelligence` | Lower-layer shared kit |
| `browser/` | `weavert-kit-common-browser` | `weavert_kit_common_browser` | `weavert-bridge-browser` | Lower-layer shared kit |
| `local-os/` | `weavert-kit-common-local-os` | `weavert_kit_common_local_os` | `weavert-bridge-local-os` | Lower-layer shared kit |
| `pim/` | `weavert-kit-common-pim` | `weavert_kit_common_pim` | `weavert-bridge-pim` | Lower-layer shared kit |

## Exposure tier

- These packages are public lower-layer building blocks that scenario kits compose.
- Their runtime activation names intentionally differ from the public install names.

## Ownership rule

- Put reusable product-kit bridges here when more than one scenario pack should compose them.
- Keep product-profile defaults in the scenario-pack packages above this layer.

## Easy boundary checks

- `retrieval` ranks and cites grounding you already have.
- `web-research` runs read-only public-web research and exposes low-level search, fetch, and find primitives.
- `browser` uses a host-mediated browser bridge for state, navigation, and interaction.
- `local-os` exposes generic local-machine surfaces such as files, clipboard, notifications, and processes.
- `pim` exposes structured personal-data surfaces such as calendars, contacts, reminders, and tasks.

## See also

- `../README.md`
- `retrieval/README.md`
- `web-research/README.md`
- `git/README.md`
- `browser/README.md`
- `../../../docs/maintainers/pypi-release-readiness.md`
- `../../../docs/concepts/packages-and-scenario-packs.md`
