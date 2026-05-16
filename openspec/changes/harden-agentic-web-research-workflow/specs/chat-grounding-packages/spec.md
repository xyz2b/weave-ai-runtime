## MODIFIED Requirements

### Requirement: The repository SHALL provide a read-only web grounding package for chat products
The repository SHALL provide an official read-only web grounding package with chat-safe web search and fetch surfaces plus a hardened high-level `web_research` workflow for bounded open or focused source discovery, inspected-page retrieval, page-local evidence extraction, and citation-ready source handling.

#### Scenario: Chat product enables the read-only web package
- **WHEN** an adopter enables the official web grounding package alongside a chat profile
- **THEN** the runtime SHALL expose read-only web grounding surfaces suitable for chat answers
- **AND** the runtime SHALL expose a high-level `web_research` surface suitable for bounded open-ended or focused research
- **AND** the default package contract SHALL not require implicit workspace mutation or shell execution

#### Scenario: Chat product invokes open-ended web research
- **WHEN** a chat product invokes `web_research` for an open-ended question
- **THEN** the workflow SHALL allow exploratory source discovery through soft preferences and bounded budgets
- **AND** it SHALL preserve hard safety policy, blocked domains, public-host validation, and read-only behavior

#### Scenario: Chat product invokes focused web research
- **WHEN** a chat product invokes `web_research` with explicit hard allowed domains or focused mode
- **THEN** the workflow SHALL enforce those domain constraints across delegated search, fetch, find, and concurrent URL inspection
- **AND** it SHALL surface policy-blocked or partial-result metadata when the focused constraints prevent a complete answer

## ADDED Requirements

### Requirement: The shared common web package SHALL return reusable evidence for chat grounding
The shared `common/web` package SHALL ensure the high-level `web_research` result contains reusable sources, inspected evidence, trace summary, policy metadata, and budget metadata derived from actual read-only web operations.

#### Scenario: Chat answer builder consumes web research output
- **WHEN** a chat answer builder receives a `web_research` result
- **THEN** it SHALL be able to consume structured `sources` and `evidence` without parsing the full child-run transcript
- **AND** those structures SHALL reflect actual search, fetch, find, or concurrent inspection operations performed by the workflow

### Requirement: The shared common web package SHALL keep concurrent page inspection bounded and read-only
The shared `common/web` package SHALL support concurrent page inspection only as a bounded read-only research optimization and SHALL NOT expand into browser navigation, shell execution, or workspace mutation.

#### Scenario: Chat workflow inspects multiple candidate pages
- **WHEN** the chat-facing web workflow inspects multiple candidate URLs concurrently
- **THEN** every page inspection SHALL remain a read-only fetch or inspection operation
- **AND** the workflow SHALL enforce maximum concurrency, shared fetch budget, domain policy, and bounded trace reporting
- **AND** browser mediation SHALL remain outside the shared common web package boundary

### Requirement: The shared common web package SHALL publish source-matching build artifacts
The shared `common/web` package SHALL keep generated local build and distribution artifacts aligned with source when those artifacts are present in the repository and used for release-readiness checks.

#### Scenario: Maintainer inspects local distributable artifacts
- **WHEN** a maintainer inspects the common web package wheel or source distribution present in the repository
- **THEN** those artifacts SHALL contain the same public `web_research`, `web-searcher`, and low-level read-only web surfaces as the source package
- **AND** release-readiness checks SHALL fail or surface a clear mismatch if generated artifacts lag the source implementation
