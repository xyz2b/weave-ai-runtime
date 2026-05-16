## MODIFIED Requirements

### Requirement: The coding scenario-pack contract SHALL declare its shared coding dependencies
The official coding scenario-pack contract SHALL identify its shared coding package dependencies and expected tool inventory as a flat list of tool invocation names when those dependencies are selected, and SHALL use the unified common web research package for external technical web lookup rather than a separate coding-only web research package.

#### Scenario: Caller inspects the coding scenario-pack contract
- **WHEN** a caller resolves the official coding scenario-pack capability
- **THEN** the contract SHALL identify the shared coding packages it expects to compose
- **AND** it SHALL publish the expected tool invocation-name inventory that depends on those shared packages being enabled
- **AND** coding-oriented external web lookup SHALL be represented by unified `web_research` and `web_*` primitives with a coding research profile

## ADDED Requirements

### Requirement: Coding web lookup SHALL use the unified common web research package
The repository SHALL provide coding-oriented external technical lookup through the unified common web research package rather than through a separate coding-only product-kit package.

#### Scenario: Coding product needs external technical evidence
- **WHEN** a coding-oriented workflow needs documentation, changelog, release-note, GitHub, or API reference evidence from the public web
- **THEN** it SHALL invoke the unified web research surfaces with profile `coding` or an equivalent coding default
- **AND** it SHALL NOT require `technical_web_search`, `technical_web_fetch`, or `technical_web_find` public tools

### Requirement: Coding-specific web evidence SHALL be represented as coding facets
Coding-oriented web research SHALL preserve version scope, API names, compatibility notes, and breaking-change information as coding profile facets on the unified `web_research` result.

#### Scenario: Coding research detects version-specific evidence
- **WHEN** a coding-oriented workflow asks for external technical evidence scoped to a version, release line, API, or compatibility concern
- **THEN** `web_research` SHALL return common top-level sources and evidence
- **AND** version scope, API names, compatibility notes, and breaking-change fields SHALL appear under `facets.coding`

### Requirement: Coding web profile SHALL prioritize authoritative technical sources
The coding research profile SHALL prefer official documentation, release notes, changelogs, source repositories, issue trackers, and authoritative project pages when ranking sources for technical answers.

#### Scenario: Coding research ranks candidate sources
- **WHEN** search returns official documentation, release notes, source repository content, blog posts, and low-authority mirrors
- **THEN** the coding research profile SHALL rank official and source-owned references ahead of lower-authority sources when they are relevant
- **AND** it SHALL surface version mismatch or insufficient authoritative evidence as a gap or conflict when applicable
