# Shared Product-Kit Packages

This family groups reusable product-kit packages shared across multiple scenario packs.

## What this family owns

- reusable bridges such as retrieval, web, git, browser, local-OS, PIM, and workspace intelligence
- shared product-kit packages that stay below scenario-pack ownership

## Concrete packages

- `retrieval/` -> `weavert_kit_common_retrieval`
- `web/` -> `weavert_kit_common_web`
- `git/` -> `weavert_kit_common_git`
- `workspace-intelligence/` -> `weavert_kit_common_workspace_intelligence`
- `browser/` -> `weavert_kit_common_browser`
- `local-os/` -> `weavert_kit_common_local_os`
- `pim/` -> `weavert_kit_common_pim`

## Ownership rule

- Put reusable product-kit bridges here when more than one scenario pack should compose them.
- Keep product-profile defaults in the scenario-pack packages above this layer.

## See also

- `../README.md`
- `retrieval/README.md`
- `git/README.md`
- `browser/README.md`
- `../../../docs/concepts/packages-and-scenario-packs.md`
