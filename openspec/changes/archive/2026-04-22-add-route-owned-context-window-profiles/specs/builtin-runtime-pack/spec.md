## MODIFIED Requirements

### Requirement: Built-in runtime pack includes a first-party OpenAI provider baseline
The runtime SHALL bundle a first-party OpenAI provider integration as part of the built-in runtime pack, together with default named-route-ready definitions or equivalent provider wiring that hosts may use directly or override.

#### Scenario: Runtime boots without custom provider integrations
- **WHEN** the runtime starts with only bundled runtime definitions
- **THEN** it SHALL still expose a usable first-party OpenAI provider integration baseline
- **AND** SHALL allow hosts to supply credentials, route overrides, or model overrides without requiring a separate third-party OpenAI plugin to be installed first

#### Scenario: Built-in OpenAI provider baseline participates in context-window-aware execution
- **WHEN** the bundled first-party OpenAI provider integration is used through a named route
- **THEN** it SHALL be able to provide context window profiles and minimal recovery classification hints under the same contract as third-party integrations
- **AND** SHALL NOT require special-case runtime logic outside the shared integration and route-resolution path

#### Scenario: Built-in OpenAI provider baseline exposes canonical route names and env overrides
- **WHEN** the runtime loads its bundled first-party OpenAI provider baseline
- **THEN** it SHALL expose a default provider binding named `openai-prod`
- **AND** SHALL expose a default named route `openai_default`
- **AND** SHALL recognize `OPENAI_API_KEY` for credentials together with optional `OPENAI_BASE_URL` and `OPENAI_MODEL` overrides or equivalent host-supplied replacements

#### Scenario: Missing bundled OpenAI credentials does not remove the route definition
- **WHEN** the bundled OpenAI route definitions are available but `OPENAI_API_KEY` has not been supplied and the host has not overridden credentials
- **THEN** the runtime SHALL still allow the OpenAI route baseline to be discovered and overridden
- **AND** SHALL fail invocation with a structured configuration or credential error rather than silently removing the built-in route from discovery
