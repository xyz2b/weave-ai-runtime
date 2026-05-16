## ADDED Requirements

### Requirement: Local-assistant browser handoff SHALL consume unified web research outputs
Local-assistant profiles SHALL use the unified common web research outputs for read-only public-web lookup before escalating to browser bridge surfaces.

#### Scenario: Local assistant escalates from web research to browser mediation
- **WHEN** a local-assistant workflow determines that read-only web search, fetch, or evidence extraction is insufficient and browser state or interaction is required
- **THEN** it SHALL pass source, page, evidence, or research-trace handles from the unified web research output into the staged browser bridge handoff
- **AND** browser navigation, clicking, form filling, and DOM interaction SHALL remain owned by the browser bridge package

### Requirement: Local-assistant web defaults SHALL not create separate web tool names
Local-assistant profiles SHALL declare web research defaults such as profile, source preferences, browser handoff metadata, or budget posture when read-only web research is enabled, but SHALL use the same unified `web_research` and low-level `web_*` public tool vocabulary as other profiles.

#### Scenario: User inspects local-assistant web inventory
- **WHEN** an adopter inspects a local-assistant profile with read-only web research enabled
- **THEN** the profile SHALL expose the unified web research tool vocabulary
- **AND** it SHALL NOT expose local-assistant-specific public web search, fetch, or find tool-name variants
