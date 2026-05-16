## 1. Package Identity and Layout

- [x] 1.1 Confirm the unified public package identity: `packages/product-kits/common/web-research`, install name `weavert-kit-common-web-research`, import root `weavert_kit_common_web_research`, and runtime activation `weavert-shared-web-research`.
- [x] 1.2 Move the current `packages/product-kits/common/web` high-level `web_research`, worker-agent, ledger, low-level primitive, README, build metadata, and package manifest behavior into `packages/product-kits/common/web-research`.
- [x] 1.3 Remove the separate coding-only adapter identity from `packages/product-kits/common/web-research` while preserving its useful technical lookup behavior inside the unified package.
- [x] 1.4 Remove `packages/product-kits/common/web` as a first-party package root after all package references have migrated.
- [x] 1.5 Reconcile active or completed-but-unarchived web changes and specs that still assume separate chat/coding web packages or preserved `grounding_web_*` and `technical_web_*` public names.
- [x] 1.6 Update workspace layout checks, publish package ordering, public package catalog data, import smoke lists, and release-readiness metadata for the unified web research package.

## 2. Unified Public Tool Vocabulary

- [x] 2.1 Replace public `grounding_web_search`, `grounding_web_fetch`, and `grounding_web_find` definitions with unified `web_search`, `web_fetch`, and `web_find` definitions backed by the same shared primitive core.
- [x] 2.2 Replace public `technical_web_search`, `technical_web_fetch`, and `technical_web_find` definitions with `web_research(profile="coding")` behavior and the unified low-level `web_*` primitives.
- [x] 2.3 Remove first-party public registrations, exports, docs, tests, and scenario inventories for `grounding_web_*`, `technical_web_*`, and `web_research_fetch_many` names.
- [x] 2.4 Preserve bounded concurrent page inspection only as a package-owned internal helper behind `web_research`, not as a public tool inventory entry.
- [x] 2.5 Keep built-in or devtools `web_search` and `web_fetch` compatibility surfaces routed through `weavert-web-research` without creating separate profile-specific names.
- [x] 2.6 Update the `web-searcher` delegated worker prompt and authorized tool pool to use the unified `web_*` primitives and package-owned helper tools only.

## 3. ResearchProfile Strategy Model

- [x] 3.1 Add the generic `ResearchProfile` schema, loop state, provider/freshness metadata propagation, and strategy hook contract to the framework web research core.
- [x] 3.2 Add first-party profile definitions for `general`, `coding`, `business`, `academic`, `legal_compliance`, and `product_shopping` in the unified product-kit package.
- [x] 3.3 Wire `web_research` input validation and normalization to accept an explicit `profile` field and default or classify to `general` when absent.
- [x] 3.4 Apply profile source-ranking defaults for coding, business, academic, legal/compliance, and product-shopping source priorities.
- [x] 3.5 Ensure profile selection is preserved in `research_trace` and can be set by scenario-pack defaults.

## 4. Unified Research Result Envelope

- [x] 4.1 Refactor `web_research` output to the common envelope: `answer`, `confidence`, `sources`, `evidence`, `conflicts`, `gaps`, `freshness`, `provider`, `provider_selection`, `provider_fallback`, `stop_reason`, `research_trace`, and `facets`.
- [x] 4.2 Move coding-specific fields such as `version_scope`, API names, compatibility notes, and breaking changes under `facets.coding`.
- [x] 4.3 Add profile facet builders for business, academic, legal/compliance, and product-shopping metadata, even if the first implementation starts with conservative empty or partially populated facets.
- [x] 4.4 Update ledger aggregation so sources, evidence, conflicts, gaps, freshness, provider metadata, provider fallback metadata, and research trace are derived from actual web operations rather than unverified child metadata.
- [x] 4.5 Update stop-reason classification to distinguish sufficient evidence, partial result, budget exhaustion, policy blocked, freshness unsupported, unresolved conflict, and remaining gaps.

## 5. Scenario and Browser Boundary Integration

- [x] 5.1 Update chat, coding, and local-assistant scenario package manifests to depend on the unified common web research package when web information retrieval is enabled.
- [x] 5.2 Update scenario tool inventories so all profiles expose `web_research` and unified `web_*` primitives instead of `grounding_web_*` or `technical_web_*`.
- [x] 5.3 Set required profile defaults in scenario composition: `coding` for coding external technical lookup, `general` for chat/general grounding unless a more specific first-party profile is declared, and an explicit declared read-only web profile for local-assistant web research.
- [x] 5.4 Preserve local-assistant staged browser handoff by passing unified source, page, evidence, and research-trace handles into browser bridge payloads without adding browser actions to web research.
- [x] 5.5 Update scenario-pack validation to assert unified web package visibility and absence of obsolete web tool families.

## 6. Documentation and Release Artifacts

- [x] 6.1 Rewrite `packages/product-kits/common/web-research/README.md` and localized docs to describe the unified public web research package, profile usage, and browser boundary.
- [x] 6.2 Update product-kit, framework-pack, package catalog, package-combination, and adoption guidance docs so users see one common web research package choice.
- [x] 6.3 Update references in OpenSpec-facing docs, package tables, and examples from `common/web` or separate coding web research package language to the unified package.
- [x] 6.4 Regenerate or remove stale build and distribution artifacts for the old and new web product-kit packages according to the repository's release-readiness checks.
- [x] 6.5 Update any Chinese README or guidance copies that mention the old package split or old tool names.

## 7. Tests and Validation

- [x] 7.1 Update package import, package shape, package manifest, and publish-layout tests for the unified web research package.
- [x] 7.2 Update web research workflow tests for unified `web_*` primitives, `ResearchProfile` selection, profile defaults, provider/fallback metadata, and the new output envelope.
- [x] 7.3 Add tests for `facets.coding` version scope and API metadata replacing top-level or `technical_web_*`-specific outputs.
- [x] 7.4 Add tests for business, academic, legal/compliance, and product-shopping profile defaults, source ranking hints, freshness requirements, conflicts, gaps, and conservative stop reasons.
- [x] 7.5 Update built-in/devtools tests to confirm their web compatibility tools route through `weavert-web-research`.
- [x] 7.6 Run targeted web research, scenario-pack, workflow-testing, package-layout, and docs/catalog validation suites.
- [x] 7.7 Run `openspec validate unify-web-research-capability --strict` after implementation updates and fix any spec/task drift.
