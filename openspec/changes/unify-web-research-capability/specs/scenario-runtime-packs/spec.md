## MODIFIED Requirements

### Requirement: Scenario-pack references that compose the shared common web package SHALL publish both the high-level and low-level web surfaces
Official scenario-pack references that compose the unified common web research package SHALL publish `web_research` as the preferred high-level read-only web surface alongside the lower-level read-only `web_*` primitives contributed by that package.

#### Scenario: User inspects the official chat reference pack
- **WHEN** an adopter inspects the official chat reference scenario-pack contract after the unified common web research package exposes `web_research`
- **THEN** the expected tool inventory for that reference pack SHALL include `web_research` plus the unified low-level read-only web primitives such as `web_search`, `web_fetch`, and `web_find`
- **AND** the contract SHALL continue to identify those lower-level read-only web surfaces as part of the unified common web research package contribution
- **AND** the contract SHALL NOT list `grounding_web_*` or `web_research_fetch_many` public tool names

#### Scenario: User inspects the official local-assistant reference pack
- **WHEN** an adopter inspects the official local-assistant reference scenario-pack contract after the unified common web research package exposes `web_research`
- **THEN** the expected tool inventory for that reference pack SHALL include `web_research` plus the unified low-level read-only web primitives such as `web_search`, `web_fetch`, and `web_find`
- **AND** that contract SHALL keep browser-bridge mediation as a separate concern from the read-only shared web research surface
- **AND** the contract SHALL NOT list `grounding_web_*` or `web_research_fetch_many` public tool names

## ADDED Requirements

### Requirement: Scenario-pack references SHALL compose one common web research package
Official scenario-pack references that need public-web information retrieval SHALL compose the unified common web research package rather than separate chat web and coding web research packages.

#### Scenario: User compares scenario-pack web dependencies
- **WHEN** an adopter compares chat, coding, local-assistant, or future business, academic, legal, or shopping profile references
- **THEN** every profile that needs read-only web information retrieval SHALL identify the same unified common web research package dependency
- **AND** profile-specific behavior SHALL be documented as default `ResearchProfile` configuration instead of separate package selection

### Requirement: Scenario-pack references SHALL set web profile defaults without changing tool names
Official scenario-pack references SHALL set default web research profiles, budgets, source preferences, and freshness posture when they enable web research, but SHALL NOT expose different first-party web tool names for each product profile.

#### Scenario: Coding and chat profiles use web research
- **WHEN** an adopter inspects the official coding and chat reference packs
- **THEN** both packs SHALL use the same `web_research` and low-level `web_*` tool vocabulary for public-web information retrieval
- **AND** the coding pack SHALL default to profile `coding`
- **AND** the chat pack SHALL default to profile `general` unless it declares a more specific first-party research profile

#### Scenario: Local-assistant profile uses web research
- **WHEN** an adopter inspects the official local-assistant reference pack with web research enabled
- **THEN** that pack SHALL declare its default read-only web research profile
- **AND** browser handoff defaults SHALL remain separate from the selected read-only web research profile

### Requirement: Scenario-pack validation SHALL cover unified web package visibility
Scenario-pack validation SHALL prove that web research tools are exposed through the unified common web research package and that obsolete first-party web tool families are not present.

#### Scenario: Validation checks unified web tool inventory
- **WHEN** scenario-pack validation assembles chat, coding, or local-assistant reference shapes with web research enabled
- **THEN** validation SHALL confirm that `web_research` and the unified low-level `web_*` primitives are visible as expected
- **AND** validation SHALL confirm that `grounding_web_*`, `technical_web_*`, and `web_research_fetch_many` public tool names are absent from first-party inventories
