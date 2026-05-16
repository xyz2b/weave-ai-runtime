## ADDED Requirements

### Requirement: Official adoption guidance SHALL present one common web research package
The repository SHALL document one common web research package as the adopter-facing choice for read-only public-web information retrieval.

#### Scenario: User chooses a web package
- **WHEN** a user reads package-combination or public package catalog guidance and wants web search, page fetch, page-local evidence finding, or high-level web research
- **THEN** the guidance SHALL direct the user to the unified common web research package
- **AND** it SHALL NOT require the user to choose between separate chat web and coding web research packages

### Requirement: Official adoption guidance SHALL distinguish web research from browser interaction
The repository SHALL keep read-only web research guidance separate from browser bridge guidance.

#### Scenario: User needs browser interaction
- **WHEN** a user needs browser state, navigation, clicking, form filling, authenticated browsing, or DOM interaction
- **THEN** the guidance SHALL direct the user to the browser bridge package
- **AND** it SHALL describe the unified common web research package as read-only information retrieval rather than browser control

### Requirement: Official adoption guidance SHALL explain profile-driven web research
The repository SHALL explain that web research profiles change strategy and output facets rather than requiring separate public tools.

#### Scenario: User needs coding or business research
- **WHEN** a user wants coding documentation lookup, business research, academic evidence, legal/compliance checking, or product shopping research
- **THEN** the guidance SHALL instruct the user to use `web_research` with an appropriate profile or scenario default
- **AND** it SHALL explain that profile-specific fields appear under `facets`
