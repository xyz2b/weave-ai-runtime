# Shared Product-Kit Packages

This family groups reusable product-kit packages shared across multiple scenario packs.

## What this family owns

- reusable bridges such as retrieval, web, git, browser, local-OS, PIM, and workspace intelligence
- shared product-kit packages that stay below scenario-pack ownership

## Concrete packages

| Package root | Install name | Import root | Runtime activation | Exposure tier |
| --- | --- | --- | --- | --- |
| `retrieval/` | `weavert-kit-common-retrieval` | `weavert_kit_common_retrieval` | `weavert-shared-retrieval` | Lower-layer shared kit |
| `web/` | `weavert-kit-common-web` | `weavert_kit_common_web` | `weavert-bridge-web` | Lower-layer shared kit |
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

## See also

- `../README.md`
- `retrieval/README.md`
- `git/README.md`
- `browser/README.md`
- `../../../docs/maintainers/pypi-release-readiness.md`
- `../../../docs/concepts/packages-and-scenario-packs.md`
