## MODIFIED Requirements

### Requirement: The shared web research core SHALL remain the primitive substrate for higher-level workflows
The framework-level shared web research package SHALL remain the canonical primitive substrate for normalized web search, fetch, page-local find, policy enforcement, freshness handling, provider selection, result normalization, and reusable research-loop mechanics, and SHALL NOT become the public owner of the user-facing `web_research` tool package.

#### Scenario: User inspects the framework-level shared web research package boundary
- **WHEN** an adopter inspects the package contract for the framework-level shared web research implementation project
- **THEN** that package SHALL be described as the shared core for backends, policy, normalization, primitive web execution helpers, and reusable research-loop mechanics
- **AND** the higher-level `web_research` tool surface SHALL remain owned by the unified common web research product-kit package layered on top of that core

### Requirement: Higher-level web workflows SHALL compose the shared core through package adapters
Any official higher-level web research workflow surface SHALL consume the shared web research core through the unified common web research product-kit package rather than by redefining a standalone primitive implementation path or by splitting profile-specific product-kit packages.

#### Scenario: Official high-level web workflow performs delegated evidence gathering
- **WHEN** an official higher-level web workflow performs search, inspected-page retrieval, page-local evidence gathering, source ranking, or synthesis
- **THEN** that workflow SHALL reuse the shared web research core through the unified common web research package
- **AND** the repository SHALL avoid introducing a second canonical primitive implementation path for the same web policy and normalization concerns
- **AND** profile-specific behavior SHALL be represented through research strategy inputs rather than separate public web tool families

## ADDED Requirements

### Requirement: Web research SHALL expose one unified public product-kit package
The repository SHALL provide one user-facing common web research product-kit package for web information retrieval, using `web-research` naming for the public package identity before external adoption.

#### Scenario: User chooses a common web package
- **WHEN** an adopter wants read-only web information retrieval without taking a full scenario profile
- **THEN** the repository SHALL direct the adopter to the unified common web research package
- **AND** the repository SHALL NOT present separate chat web and coding web research product-kit packages as competing user-facing choices

### Requirement: Web research SHALL use one public web tool vocabulary
The unified common web research package SHALL expose `web_research` as the recommended high-level tool and SHALL expose `web_search`, `web_fetch`, and `web_find` as the single low-level primitive family for search, page fetch, and page-local find.

#### Scenario: User inspects unified web tool inventory
- **WHEN** an adopter inspects the public tool inventory contributed by the unified common web research package
- **THEN** the inventory SHALL include `web_research`
- **AND** it SHALL include `web_search`, `web_fetch`, and `web_find`
- **AND** it SHALL NOT expose first-party public `grounding_web_*`, `technical_web_*`, or `web_research_fetch_many` tool names

### Requirement: Web research SHALL model product differences as ResearchProfile strategies
The shared web research capability SHALL define a `ResearchProfile` strategy model that can vary query planning, source ranking, freshness policy, evidence schema, conflict handling, stop conditions, output facets, and defaults without requiring profile-specific public packages or tool families. The framework-level web research core SHALL own the generic schema, loop state, provider/freshness metadata propagation, and strategy hook contracts; the unified product-kit package SHALL own first-party profile defaults and facet builders.

#### Scenario: Caller invokes a profile-specific research workflow
- **WHEN** a caller invokes `web_research` with profile `coding`, `general`, `business`, `academic`, `legal_compliance`, or `product_shopping`
- **THEN** the workflow SHALL use the shared research loop and shared primitive core
- **AND** profile-specific behavior SHALL come from the selected `ResearchProfile` strategy
- **AND** the selected profile SHALL be visible in research trace metadata

### Requirement: Web research SHALL standardize high-level research results
The high-level `web_research` result SHALL use a common output envelope for answer, confidence, sources, evidence, conflicts, gaps, freshness, provider, provider selection, provider fallback, stop reason, and research trace.

#### Scenario: Caller consumes research output across profiles
- **WHEN** a caller receives a `web_research` result from any supported profile
- **THEN** the caller SHALL be able to read common top-level fields for answer, confidence, sources, evidence, conflicts, gaps, freshness, provider, provider selection, provider fallback, stop reason, and research trace
- **AND** the caller SHALL NOT need profile-specific parsing to determine whether evidence was sufficient, stale, conflicting, blocked, or incomplete

### Requirement: Web research profile-specific data SHALL live under facets
The high-level `web_research` result SHALL place profile-specific structured data under `facets.<profile>` rather than adding profile-specific fields to the top-level result shape.

#### Scenario: Coding profile reports version information
- **WHEN** `web_research` runs with profile `coding` and detects version scope, API names, or breaking changes
- **THEN** those fields SHALL be placed under `facets.coding`
- **AND** the top-level result envelope SHALL remain consistent with non-coding profiles

#### Scenario: Business profile reports comparison information
- **WHEN** `web_research` runs with profile `business` and detects companies, competitors, timelines, comparison axes, or market claims
- **THEN** those fields SHALL be placed under `facets.business`
- **AND** the top-level result envelope SHALL remain consistent with non-business profiles
