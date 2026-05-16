## MODIFIED Requirements

### Requirement: The repository SHALL provide a read-only web grounding package for chat products
The repository SHALL provide an official unified common web research package with read-only web search, fetch, page-local find, and high-level `web_research` surfaces suitable for chat grounding, while preserving the same package for non-chat web information retrieval profiles.

#### Scenario: Chat product enables the read-only web package
- **WHEN** an adopter enables the official unified common web research package alongside a chat profile
- **THEN** the runtime SHALL expose read-only web research surfaces suitable for chat answers
- **AND** the runtime SHALL expose a high-level `web_research` surface suitable for bounded open-ended or focused research
- **AND** the default package contract SHALL not require implicit workspace mutation or shell execution

#### Scenario: Chat product invokes open-ended web research
- **WHEN** a chat product invokes `web_research` for an open-ended question
- **THEN** the workflow SHALL allow exploratory source discovery through soft preferences and bounded budgets
- **AND** it SHALL preserve hard safety policy, blocked domains, public-host validation, read-only behavior, and structured gap or conflict reporting

#### Scenario: Chat product invokes focused web research
- **WHEN** a chat product invokes `web_research` with explicit hard allowed domains or focused mode
- **THEN** the workflow SHALL enforce those domain constraints across delegated search, fetch, find, and concurrent URL inspection
- **AND** it SHALL surface policy-blocked or partial-result metadata when the focused constraints prevent a complete answer

### Requirement: The shared common web package SHALL preserve both AI-first and primitive read-only web surfaces
The unified shared common web research package SHALL expose the high-level `web_research` surface as the preferred AI-first entrypoint while preserving one general low-level read-only web primitive family for callers that need direct control or custom orchestration.

#### Scenario: User inspects the shared common web research package inventory
- **WHEN** an adopter inspects the callable surfaces exposed by the official unified common web research package
- **THEN** that package SHALL expose the high-level `web_research` surface
- **AND** it SHALL also expose lower-level `web_search`, `web_fetch`, and `web_find` as independently callable package capabilities
- **AND** it SHALL NOT expose separate chat-only `grounding_web_*` public primitives

### Requirement: The shared common web package SHALL keep the high-level workflow read-only
The high-level `web_research` surface in the unified common web research package SHALL preserve the same read-mostly boundary as the rest of the package and SHALL NOT imply browser navigation ownership, shell execution, or workspace mutation.

#### Scenario: User inspects the high-level web workflow boundary
- **WHEN** an adopter inspects the package contract for the unified common web research package
- **THEN** the package SHALL remain suitable for read-mostly grounded chat composition
- **AND** browser mediation, shell execution, and workspace-mutation behavior SHALL remain outside the package boundary

### Requirement: The shared common web package SHALL remain reusable by local-assistant profiles
The unified common web research package SHALL remain a supported reusable package for local-assistant composition, including `web_research` and the preserved low-level read-only web primitives, without collapsing browser-bridge ownership into the shared web package.

#### Scenario: Local-assistant product enables the shared common web research package
- **WHEN** an adopter enables the official unified common web research package alongside a local-assistant profile
- **THEN** the runtime SHALL expose `web_research` plus the shared low-level read-only web primitives from that package
- **AND** the package contract SHALL continue to treat browser navigation and browser interaction as separate browser-bridge concerns

### Requirement: The shared common web package SHALL return reusable evidence for chat grounding
The unified common web research package SHALL ensure the high-level `web_research` result contains reusable sources, inspected evidence, conflicts, gaps, trace summary, profile metadata, policy metadata, freshness metadata, provider metadata, provider fallback metadata, and budget metadata derived from actual read-only web operations.

#### Scenario: Chat answer builder consumes web research output
- **WHEN** a chat answer builder receives a `web_research` result
- **THEN** it SHALL be able to consume structured `sources` and `evidence` without parsing the full child-run transcript
- **AND** those structures SHALL reflect actual search, fetch, find, or concurrent inspection operations performed by the workflow
- **AND** material conflicts or evidence gaps SHALL be exposed as structured result fields

### Requirement: The shared common web package SHALL keep concurrent page inspection bounded and read-only
The unified common web research package SHALL support concurrent page inspection only as a bounded read-only research optimization and SHALL NOT expand into browser navigation, shell execution, or workspace mutation.

#### Scenario: Chat workflow inspects multiple candidate pages
- **WHEN** the web research workflow inspects multiple candidate URLs concurrently
- **THEN** every page inspection SHALL remain a read-only fetch or inspection operation
- **AND** the workflow SHALL enforce maximum concurrency, shared fetch budget, domain policy, and bounded trace reporting
- **AND** browser mediation SHALL remain outside the unified common web research package boundary

### Requirement: The shared common web package SHALL publish source-matching build artifacts
The unified common web research package SHALL keep generated local build and distribution artifacts aligned with source when those artifacts are present in the repository and used for release-readiness checks.

#### Scenario: Maintainer inspects local distributable artifacts
- **WHEN** a maintainer inspects the unified common web research package wheel or source distribution present in the repository
- **THEN** those artifacts SHALL contain the same public `web_research`, `web-searcher`, and low-level read-only web surfaces as the source package
- **AND** release-readiness checks SHALL fail or surface a clear mismatch if generated artifacts lag the source implementation
