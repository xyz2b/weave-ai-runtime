# Product Kits

This family root indexes concrete product-kit packages.
It owns scenario packs plus shared product-kit packages.

## What this family owns

- scenario packs that publish product-profile defaults
- shared product-kit packages reused across multiple scenario packs

## Public release scope

- Every concrete package under this family is a public PyPI project.
- Scenario kits are the higher-layer profile entrypoints.
- Shared common kits remain separately publishable lower-layer building blocks.

## Scenario-pack kits

| Package root | Install name | Import root | Runtime activation | Exposure tier |
| --- | --- | --- | --- | --- |
| `chat/` | `weavert-kit-chat` | `weavert_kit_chat` | `weavert-scenario-chat` | Higher-layer profile entrypoint |
| `coding/` | `weavert-kit-coding` | `weavert_kit_coding` | `weavert-scenario-coding` | Higher-layer profile entrypoint |
| `local-assistant/` | `weavert-kit-local-assistant` | `weavert_kit_local_assistant` | `weavert-scenario-local-assistant` | Higher-layer profile entrypoint |

## Shared product-kit packages

| Package root | Install name | Import root | Runtime activation | Exposure tier |
| --- | --- | --- | --- | --- |
| `common/retrieval/` | `weavert-kit-common-retrieval` | `weavert_kit_common_retrieval` | `weavert-shared-retrieval` | Lower-layer shared kit |
| `common/web-research/` | `weavert-kit-common-web-research` | `weavert_kit_common_web_research` | `weavert-shared-web-research` | Unified web research kit with profile-driven `web_research`, provider metadata, freshness outcomes, facets, and low-level read-only primitives |
| `common/git/` | `weavert-kit-common-git` | `weavert_kit_common_git` | `weavert-shared-git` | Lower-layer shared kit |
| `common/workspace-intelligence/` | `weavert-kit-common-workspace-intelligence` | `weavert_kit_common_workspace_intelligence` | `weavert-shared-workspace-intelligence` | Lower-layer shared kit |
| `common/browser/` | `weavert-kit-common-browser` | `weavert_kit_common_browser` | `weavert-bridge-browser` | Lower-layer shared kit |
| `common/local-os/` | `weavert-kit-common-local-os` | `weavert_kit_common_local_os` | `weavert-bridge-local-os` | Lower-layer shared kit |
| `common/pim/` | `weavert-kit-common-pim` | `weavert_kit_common_pim` | `weavert-bridge-pim` | Lower-layer shared kit |

## Composition summary

- `weavert_kit_chat` composes retrieval plus the unified web research kit, defaulting web research to `general`.
- `weavert_kit_coding` composes git, the unified web research kit with coding defaults, and workspace-intelligence common kits.
- `weavert_kit_local_assistant` composes retrieval, read-only web research, browser, local-OS, and PIM common kits.
- Web research provider selection is configured through the shared core (`WEAVERT_WEB_SEARCH_PROVIDER=bing-grounding`, `google-search`, `serpapi-google-search`, or `brave-search` with credentials) while public tool names remain unchanged.

## See also

- `../README.md`
- `common/README.md`
- `../../docs/maintainers/pypi-release-readiness.md`
- `../../docs/concepts/packages-and-scenario-packs.md`
- `../../docs/guides/use-scenario-packs.md`
