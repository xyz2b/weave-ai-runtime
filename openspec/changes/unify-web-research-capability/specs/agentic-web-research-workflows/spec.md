## MODIFIED Requirements

### Requirement: The repository SHALL provide a shared high-level web research tool
The repository SHALL provide an official high-level `web_research` tool in the unified common web research package so adopters can compose one AI-first web information retrieval entrypoint without choosing separate chat, coding, or profile-specific web packages.

#### Scenario: Adopter enables the shared common web research package
- **WHEN** an adopter enables the official unified common web research package in an assembled runtime
- **THEN** the runtime SHALL expose a callable `web_research` tool from that package
- **AND** the package SHALL continue to expose reusable low-level read-only web primitives for callers that need direct control
- **AND** profile-specific research behavior SHALL be selected by input profile or package defaults rather than by separate public web research tool families

### Requirement: The delegated web research agent SHALL use a controlled extensible read-only tool pool
The package-owned `web-searcher` agent SHALL use only package-authorized read-only tools that remain inside the `web_research` policy, profile, and budget envelope, but the authorized tool pool MAY include additional package-owned helper tools beyond the public low-level web primitives when those helpers preserve the shared-core ownership model.

#### Scenario: The package adds an internal helper for the research loop
- **WHEN** the unified common web research package adds a helper tool for `web-searcher`
- **THEN** that helper SHALL remain read-only and package-owned
- **AND** policy-sensitive web search, fetch, inspection, ranking, extraction, or normalization behavior SHALL reuse the framework-level shared web research core through the package adapter or an equivalent package-owned seam
- **AND** the helper SHALL NOT expand the public `web_research` contract beyond the tool-owned policy, profile, and budget controls

#### Scenario: The package keeps bounded concurrent page inspection internal
- **WHEN** the unified common web research package keeps a helper for concurrent inspection of multiple candidate URLs
- **THEN** that helper SHALL remain package-owned and available only behind `web_research` or equivalent internal orchestration
- **AND** it SHALL NOT appear in public package tool inventories as `web_research_fetch_many`

### Requirement: The `web_research` tool SHALL expose an explicit minimal input contract
The `web_research` tool input contract SHALL include a required research objective or question and explicit optional controls for profile, scope, domain restrictions, blocked domains, freshness or recency requirements, depth, source preferences, and bounded search, fetch, or inspection budgets rather than relying on an unstructured prompt-only policy bag.

#### Scenario: Caller supplies a bounded research request
- **WHEN** a caller invokes `web_research`
- **THEN** the input SHALL identify the research objective or question
- **AND** optional profile, policy, freshness, source preference, and budget fields SHALL be validated as structured tool inputs before the delegated workflow runs
- **AND** optional output-shaping hints such as desired source count or citation-oriented evidence needs SHALL NOT override validated policy, freshness, or budget controls

### Requirement: The `web_research` tool SHALL return reusable structured evidence
The `web_research` tool SHALL return a reusable structured research result that callers can use for answer assembly, follow-up inspection, citation preparation, or profile-specific reasoning, and SHALL NOT reduce the delegated workflow result to only an opaque free-form summary.

#### Scenario: Caller reuses `web_research` output for follow-up reasoning
- **WHEN** a caller invokes `web_research` and receives a successful or partially bounded result
- **THEN** the returned payload SHALL include reusable source references, inspected evidence items, conflicts, gaps, freshness metadata, provider metadata, provider fallback metadata, and terminal stop metadata gathered by the delegated workflow
- **AND** any profile-specific fields SHALL appear under `facets` rather than as top-level schema drift

### Requirement: The `web_research` tool SHALL expose an explicit minimal output contract
The `web_research` tool output contract SHALL include structured evidence and terminal workflow metadata suitable for answer assembly and observability without requiring callers to parse the delegated child-run transcript.

#### Scenario: Delegated research returns a terminal result
- **WHEN** the `web-searcher` delegated workflow completes
- **THEN** `web_research` SHALL return a structured payload with source references and inspected evidence items or excerpts when available
- **AND** it SHALL include applied profile, policy, freshness, provider, provider fallback, and budget metadata
- **AND** it SHALL include a terminal stop reason such as sufficient evidence, budget exhausted, policy blocked, freshness unsupported, conflicting evidence, gaps remaining, or partial result
- **AND** it SHALL include a bounded research trace summary or equivalent observability summary without exposing an unbounded transcript as the primary contract

### Requirement: The `web_research` workflow SHALL automatically aggregate structured evidence
The `web_research` result SHALL include structured source references, inspected evidence, conflicts, gaps, budget usage, freshness outcomes, provider metadata, provider fallback metadata, profile facets, and research trace derived from actual child-run web tool results, even when the delegated agent returns only a textual final answer.

#### Scenario: Delegated child run searches and fetches evidence then returns text
- **WHEN** the `web-searcher` child run calls low-level web tools and then returns a plain text synthesis
- **THEN** `web_research` SHALL return the synthesis as `answer`
- **AND** it SHALL populate `sources`, `evidence`, `conflicts`, `gaps`, `freshness`, `provider`, `provider_selection`, `provider_fallback`, `budget`, and `research_trace` from the recorded tool results without requiring special model-emitted terminal metadata

#### Scenario: Delegated child run returns richer structured metadata
- **WHEN** the `web-searcher` child run returns structured web research metadata in addition to recorded tool results
- **THEN** `web_research` MAY merge the structured metadata with ledger-derived evidence
- **AND** it SHALL preserve the tool-owned policy, profile, budget, freshness, and trace contract as the authoritative fallback

## ADDED Requirements

### Requirement: The web research workflow SHALL share one iterative research loop across profiles
The high-level `web_research` workflow SHALL use one iterative loop for objective interpretation, profile selection, query planning, search, source ranking, page inspection, evidence extraction, gap or conflict detection, continuation, stopping, and synthesis.

#### Scenario: Different profiles use the same research loop
- **WHEN** callers invoke `web_research` with different profiles such as `coding`, `business`, or `academic`
- **THEN** every invocation SHALL use the same core research loop stages
- **AND** the selected profile SHALL customize strategy and output facets without changing the public tool name

### Requirement: The web research workflow SHALL surface gaps and conflicts
The high-level `web_research` workflow SHALL report material evidence gaps and source conflicts as structured result fields instead of hiding them in the final answer text.

#### Scenario: Research finds conflicting evidence
- **WHEN** inspected sources disagree on a material claim
- **THEN** `web_research` SHALL include structured conflict entries that identify the competing claims or evidence
- **AND** the final confidence or stop reason SHALL reflect unresolved conflict when it affects answer reliability

#### Scenario: Research cannot fill a required evidence gap
- **WHEN** the workflow cannot find enough authoritative, fresh, or profile-appropriate evidence within policy and budget
- **THEN** `web_research` SHALL include structured gap entries
- **AND** the stop reason SHALL distinguish incomplete evidence from sufficient evidence
