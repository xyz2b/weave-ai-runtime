## Context

The repository has already moved low-level web execution into `packages/framework-packs/capabilities/web-research` and added higher-level product-kit adapters. That solved duplicated HTTP, policy, provider, and normalization logic, but the public shape is still confusing:

- `weavert-web-research` is the framework primitive core.
- `weavert-kit-common-web` owns `web_research`, `grounding_web_*`, and the delegated `web-searcher` worker.
- `weavert-kit-common-web-research` owns coding-oriented `technical_web_*` tools.

This creates two kinds of confusion. First, `weavert-kit-common-web-research` sounds like the owner of `web_research`, but it is actually a coding adapter. Second, chat and coding differ through separate package names and tool families instead of a single research workflow with profile-specific strategy.

The repository is still pre-external-adoption for these web package surfaces, so this is the right time to simplify the public API instead of carrying compatibility names indefinitely.

This change is the authoritative definition for the next web capability shape. Older active or completed-but-unarchived web changes that assumed separate chat and coding web product-kit packages, or preservation of `grounding_web_*` and `technical_web_*` public names, must be reconciled to this definition before archival or implementation completion.

## Goals / Non-Goals

**Goals:**

- Keep exactly one canonical primitive web information retrieval implementation in the framework-pack layer.
- Provide exactly one user-facing common web research product-kit package.
- Rename the user-facing common web package around `web-research` naming so the package name matches the primary `web_research` capability.
- Replace chat/coding-specific tool families with one public high-level `web_research` surface and one low-level `web_*` primitive family.
- Model `coding`, `general`, `business`, `academic`, `legal_compliance`, and `product_shopping` differences as `ResearchProfile` strategies.
- Standardize the high-level output envelope and isolate profile-specific data under `facets`.
- Remove `grounding_web_*` and `technical_web_*` public surfaces during this change rather than creating a deprecation period.

**Non-Goals:**

- Moving the primitive core into a product-kit package.
- Adding browser navigation, clicking, form filling, authenticated browsing, or DOM interaction to web research.
- Building provider-specific ranking parity with hosted search or research products.
- Making every listed research profile equally sophisticated in the first implementation. The first version may ship profile definitions and schema support before all profile heuristics are deeply tuned.
- Preserving compatibility for newly introduced `grounding_web_*` or `technical_web_*` names.

## Decisions

### Decision: Keep a two-layer architecture, but expose only one user-facing web research kit

The framework-level `weavert-web-research` package remains the primitive substrate. It owns provider selection, safe URL handling, public-host validation, redirect policy, domain policy, freshness metadata, search, page fetch/read, page-local find, result normalization, evidence structures, and reusable research-loop mechanics.

The product-kit layer exposes one common web research package. That package should use `web-research` naming for the package directory, install name, import root, runtime activation, package manifest, and documentation. The intended public identity should become:

- package root: `packages/product-kits/common/web-research/`
- install name: `weavert-kit-common-web-research`
- import root: `weavert_kit_common_web_research`
- runtime activation: `weavert-shared-web-research`

This package owns the user-facing tools and profile defaults. It consumes the framework core; it does not reimplement primitive web behavior.

Alternative considered:

- Keep `common/web` as the public package and delete only the coding package. Rejected because the name `web` is too broad and does not match the primary public capability, while `web-research` is clearer for information retrieval.
- Move the framework core into the product-kit package. Rejected because framework workflows and product kits must share the primitive core without framework-pack reverse dependencies on product kits.

### Decision: Migrate implementation into the `web-research` package name, not into two product-kit packages

The existing `packages/product-kits/common/web-research` package will become the unified public package location. The existing `common/web` implementation content should be moved or copied into it, then expanded with the profile strategy model and unified primitives. The separate coding-only adapter identity should disappear.

Because there are no external users yet, the implementation may remove the old `common/web` package instead of publishing a compatibility wheel. If local build artifacts or workspace layout checks reference the old package, they should be updated in the same change.

Alternative considered:

- Leave both package directories and make one re-export the other. Rejected because the goal is to reduce package choices before users depend on them.

### Decision: Use one public tool vocabulary

The unified public tools should be:

- `web_research`: the recommended high-level iterative research workflow.
- `web_search`: low-level search primitive.
- `web_fetch`: low-level page inspection primitive.
- `web_find`: low-level page-local evidence finding primitive.

`grounding_web_search`, `grounding_web_fetch`, `grounding_web_find`, `technical_web_search`, `technical_web_fetch`, and `technical_web_find` should be removed from first-party public inventories. Their behavior moves into the unified tools through `profile`, source ranking rules, evidence schemas, and facets.

`web_research_fetch_many` should also be removed from public tool inventories. Bounded concurrent page inspection may remain as an internal package-owned helper behind `web_research`, but it is not part of the public low-level primitive family.

Alternative considered:

- Keep old names as aliases. Rejected because the framework has no external users yet and aliases would preserve exactly the confusing surface this change is meant to remove.

### Decision: Generalize the research loop around `ResearchProfile`

The high-level workflow should follow one common loop:

```text
objective
   ↓
classify or accept profile
   ↓
plan queries
   ↓
search
   ↓
rank sources
   ↓
fetch/read
   ↓
extract evidence
   ↓
detect gaps/conflicts
   ↓
continue or stop
   ↓
synthesize answer
```

The framework core owns the generic `ResearchProfile` schema, reusable loop state, provider/freshness metadata propagation, and strategy hook contracts because those mechanics must be shared by built-in, devtools, and product-kit surfaces without reverse product-kit dependencies. The unified product-kit package owns first-party profile defaults, user-facing profile names, package prompts, and profile-specific facet builders.

Profiles customize the loop through data and small strategy hooks:

```python
ResearchProfile(
    name="coding",
    query_templates=...,
    source_ranking_rules=...,
    freshness_policy=...,
    evidence_schema=...,
    conflict_resolution_rules=...,
    stop_conditions=...,
    output_schema=...,
)
```

The initial profile registry should include at least:

- `general`: facts, broad coverage, authoritative and corroborating sources.
- `coding`: technical correctness, official docs, release notes, GitHub, API names, version scope, compatibility, breaking changes.
- `business`: company/product/market judgment, official pages, filings, announcements, news, reviews, timelines, competitors, comparison axes.
- `academic`: papers and research evidence, arXiv, publishers, institutional pages, citation metadata, methods, experiments, conclusions.
- `legal_compliance`: authoritative law, regulation, standards, jurisdiction, mandatory freshness, exact quotations within copyright constraints, original source precision.
- `product_shopping`: purchase decisions, official specs, prices, reviews, alternatives, risks, product comparisons.

If no profile is provided, `web_research` should classify or default to `general`, while preserving the selected profile in trace metadata.

Alternative considered:

- Create separate tools for each profile, such as `business_web_research` or `coding_web_research`. Rejected because it fragments the public API and makes future profiles expensive.

### Decision: Standardize the output envelope and put profile-specific fields under facets

The high-level `web_research` result should use a common top-level shape:

```json
{
  "answer": "...",
  "confidence": "medium",
  "sources": [],
  "evidence": [],
  "conflicts": [],
  "gaps": [],
  "freshness": {
    "requested_days": 30,
    "status": "satisfied"
  },
  "provider": {},
  "provider_selection": {},
  "provider_fallback": {},
  "stop_reason": "sufficient_evidence",
  "research_trace": {
    "profile": "business",
    "queries": [],
    "pages_read": [],
    "iterations": 2
  },
  "facets": {
    "business": {}
  }
}
```

Profile-specific fields must live under `facets.<profile>`. For example, coding-specific version information moves to `facets.coding.version_scope`; business-specific company comparisons move to `facets.business.comparison_axes`; legal-specific jurisdiction information moves to `facets.legal_compliance.jurisdiction`.

This keeps client parsing stable while allowing profile-specific richness.

Alternative considered:

- Put profile fields directly on the top-level result. Rejected because it would make the schema grow around whichever profile was implemented most recently.

### Decision: Scenario packs set defaults, not separate web tool inventories

Scenario profiles such as chat, coding, and local-assistant should compose the same unified web research package. They should set default `profile`, default budgets, default source preferences, or available browser handoff behavior where their product contract needs defaults, but they should not expose different web search/fetch/find tool names.

Coding scenario composition must default `web_research(profile="coding")` for external technical lookup. Chat or general assistants must default to `general` unless they declare a more specific first-party research profile. Local-assistant compositions must declare their default read-only web profile when they enable web research, while keeping browser handoff separate. Business, academic, legal/compliance, and product shopping profiles can be exposed through runtime or caller configuration without new packages.

Alternative considered:

- Keep coding and chat scenario packs on different shared web packages. Rejected because it preserves user confusion and duplicates package selection.

### Decision: Browser handoff remains separate

The unified web research workflow remains read-only. If a local-assistant profile needs browser state, clicking, form fill, login, or DOM interaction, it should escalate through the existing browser bridge package using source/page/evidence handles from the web research output.

Alternative considered:

- Include browser interaction as a web research profile strategy. Rejected because browser interaction has different host-owned permission and audit semantics.

## Risks / Trade-offs

- [Risk] Renaming/moving packages can churn many tests and scripts. -> Mitigation: update workspace layout, publish scripts, scenario inventory tests, docs, and release artifacts in one change; avoid leaving both packages active.
- [Risk] Removing compatibility names may break internal tests or demos. -> Mitigation: update all first-party references in the same implementation pass and validate with full targeted scenario/web suites.
- [Risk] A single `web_research` schema could become too broad. -> Mitigation: keep the top-level result envelope compact and move profile detail into `facets`.
- [Risk] Profile strategy hooks could become over-engineered before the first profiles need them. -> Mitigation: start with structured profile configuration plus small deterministic strategy functions; avoid a plugin framework unless implementation pressure demands it.
- [Risk] Legal/compliance and product shopping have high-stakes or purchase-impact expectations. -> Mitigation: encode strict freshness/source policies and visible gaps/conflicts rather than presenting weak evidence as sufficient.
- [Risk] Package rename could conflict with the current coding-only package path. -> Mitigation: treat this as a replacement: the new `web-research` package owns both general and coding behavior, and the old coding-only identity is removed.

## Migration Plan

1. Treat this change as the authoritative web capability definition and reconcile conflicting active or completed-but-unarchived web changes to this package and tool vocabulary before archival.
2. Move the current `common/web` high-level implementation into `common/web-research`, preserving the `web_research` workflow behavior as the starting point.
3. Move coding-oriented behavior from current `common/web-research` into profile-specific strategy and facets inside the unified package.
4. Add the generic `ResearchProfile` schema, loop state, provider/freshness metadata propagation, and strategy hook contracts to the framework core, then add first-party profile defaults and facet builders in the unified product-kit package.
5. Rename low-level public tools to `web_search`, `web_fetch`, and `web_find`, all backed by the same primitive core.
6. Remove first-party public references to `grounding_web_*`, `technical_web_*`, and `web_research_fetch_many`.
7. Update scenario package manifests so chat, coding, and local-assistant all compose the same web research package with different defaults.
8. Update workspace layout checks, publish package ordering, docs, READMEs, package catalog, and generated artifacts if present.
9. Add tests for package inventory, profile defaults, profile strategy behavior, unified output envelope, facets, freshness, conflicts, gaps, and browser handoff boundaries.

Rollback strategy:

- Since this is pre-external-adoption, rollback means restoring the previous package layout and tool inventory from source control. There is no requirement to support both old and new public package surfaces simultaneously.

## Open Questions

- None at this time.
