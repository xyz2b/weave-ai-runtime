## Why

The repository now has one shared web primitive core but still exposes multiple product-kit web packages and profile-specific tool families, which makes ordinary users unsure whether to choose `common/web`, `common/web-research`, `grounding_web_*`, `technical_web_*`, or `web_research`. This change unifies framework web information retrieval into one bottom-layer research core and one user-facing web research kit, with profile differences represented as strategy inputs rather than separate public packages or tool families.

## What Changes

- Treat this change as the authoritative definition for the next web capability shape, superseding older unarchived web-package split decisions where they conflict.
- Rename and reposition the user-facing common web package as the single public web research kit, using `web-research` naming for the directory, install package, import root, and runtime activation before external adoption.
- Keep the framework-level `weavert-web-research` package as the single primitive substrate for provider selection, safe search, page fetch or read, page-local find, policy enforcement, freshness handling, source normalization, and reusable research-loop mechanics.
- Fold coding-oriented web research surfaces from the separate `packages/product-kits/common/web-research` package into the unified common web research kit instead of publishing a second user-facing web package.
- Replace profile-specific public tool families such as `grounding_web_*` and `technical_web_*` with one public high-level `web_research` surface plus one consistent low-level primitive family: `web_search`, `web_fetch`, and `web_find`.
- Remove `web_research_fetch_many` from public tool inventories; if concurrent page inspection remains useful, keep it only as a package-owned internal helper behind `web_research`.
- Add a shared `ResearchProfile` strategy model so `coding`, `general`, `business`, `academic`, `legal_compliance`, and `product_shopping` behavior differs through query planning, source ranking, freshness policy, evidence schema, conflict handling, stop conditions, output facets, and defaults.
- Standardize the high-level `web_research` result shape around common fields such as `answer`, `confidence`, `sources`, `evidence`, `conflicts`, `gaps`, `freshness`, `provider`, `provider_selection`, `provider_fallback`, `stop_reason`, and `research_trace`, with profile-specific data placed under `facets`.
- Remove newly introduced profile-specific compatibility tool names during this pre-user phase rather than carrying deprecated `grounding_web_*` or `technical_web_*` public aliases forward.
- Update scenario-pack composition, package manifests, validation, release metadata, and docs so users see one web research package choice and one web research tool vocabulary.

## Capabilities

### New Capabilities

- None.

### Modified Capabilities

- `web-research-capability-profiles`: Unify web information retrieval around one primitive core, one public research workflow contract, shared research-loop mechanics, profile strategy registry, common result shape, provider/fallback metadata, and profile-specific facets.
- `chat-grounding-packages`: Replace chat-specific web package and `grounding_web_*` requirements with the unified common web research kit and general `web_*` tool vocabulary.
- `shared-coding-tool-packages`: Remove the separate coding web research package requirement and require coding web lookup to be expressed through unified `web_research(profile="coding")` and shared web primitives.
- `scenario-runtime-packs`: Update chat, coding, local-assistant, and other profile stacks to compose the unified common web research kit rather than separate chat or coding web packages.
- `agentic-web-research-workflows`: Generalize the high-level research loop and result contract beyond chat grounding so multiple research profiles share the same workflow.
- `runtime-adoption-guidance`: Update package-selection guidance so users choose one common web research package for web information retrieval, while browser interaction remains a separate bridge.
- `builtin-runtime-pack`: Repoint any built-in web compatibility names onto the unified web primitive core and common public tool vocabulary.
- `local-assistant-bridge-packages`: Keep browser escalation separate while allowing local-assistant profiles to use the same unified read-only web research outputs for staged browser handoff.

## Impact

- Affected package layout includes `packages/product-kits/common/web/`, `packages/product-kits/common/web-research/`, `packages/framework-packs/capabilities/web-research/`, package build metadata, workspace layout checks, publish scripts, generated release artifacts if present, and any active or completed-but-unarchived web changes whose older package-split assumptions conflict with this definition.
- Affected public runtime tools include `web_research`, low-level web primitives, and removal of `grounding_web_*` and `technical_web_*` from first-party public inventories.
- Affected scenario profiles include chat, coding, local-assistant, and future general/business/academic/legal/shopping compositions that should differ by profile defaults instead of separate web packages.
- Affected tests include package import smoke tests, scenario inventory tests, web research workflow tests, provider/freshness tests, output schema tests, and docs/catalog validation.
- This is intentionally allowed to be breaking for unreleased or not-yet-user-adopted web package surfaces so the public API can be simplified before external users depend on the older names.
