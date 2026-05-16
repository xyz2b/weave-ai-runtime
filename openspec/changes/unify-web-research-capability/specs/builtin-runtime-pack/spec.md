## ADDED Requirements

### Requirement: Built-in web compatibility surfaces SHALL use the unified primitive core
First-party built-in `web_search` and `web_fetch` compatibility surfaces SHALL route through the unified framework-level web research primitive core instead of maintaining independent ad hoc web retrieval logic.

#### Scenario: Runtime exposes built-in web primitives
- **WHEN** an assembled runtime exposes first-party built-in `web_search` or `web_fetch` tools
- **THEN** those tools SHALL use the same shared primitive core as the unified common web research package
- **AND** their outputs SHALL preserve compatibility fields while aligning with the shared source, policy, provider, and freshness metadata where applicable

### Requirement: Built-in web surfaces SHALL not reintroduce profile-specific tool families
The built-in runtime pack SHALL NOT reintroduce first-party `grounding_web_*` or `technical_web_*` tool families as built-in compatibility names.

#### Scenario: User inspects built-in web tool names
- **WHEN** an adopter inspects first-party built-in web tool inventory
- **THEN** the web names SHALL align with the unified `web_*` primitive vocabulary
- **AND** profile-specific behavior SHALL be selected by `web_research` profile configuration in the common web research package rather than by built-in tool-name variants
