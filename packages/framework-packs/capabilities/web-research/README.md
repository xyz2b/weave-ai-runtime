# weavert-web-research

Framework-level shared web research core used by chat, coding, local-assistant, and devtools adapters.
This package is the primitive substrate, not the public owner of the high-level `web_research` workflow surface.

## What this package owns

- normalized source, page, and citation-ready web result structures
- shared public-host and domain-policy enforcement
- a thin backend seam for search, page inspection, and page-local finding
- the default DuckDuckGo HTML plus direct-fetch backend used by first-party adapters

Higher-level packages such as `weavert-kit-common-web` compose this core through their package adapters. The shared common web kit owns the public `web_research` tool and its package-owned delegated worker.

## Canonical names

- install name: `weavert-web-research`
- import root: `weavert_web_research`

## See also

- `../../README.md`
- `../../../product-kits/common/web/README.md`
- `../../../product-kits/common/web-research/README.md`
