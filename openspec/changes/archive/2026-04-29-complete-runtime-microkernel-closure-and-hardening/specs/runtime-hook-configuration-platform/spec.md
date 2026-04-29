## MODIFIED Requirements

### Requirement: Public authoring surfaces normalize into a canonical registration schema
The runtime SHALL define a canonical public registration schema for hook authoring and SHALL normalize runtime configuration documents, supported definition-owned hook declarations, host APIs, session APIs, and turn APIs into that schema before phase-contract validation and activation.

#### Scenario: legacy skill or invocation definition hooks are up-converted before activation
- **WHEN** a skill or invocation definition uses a legacy phase-keyed `hooks` mapping such as `hooks.PreToolUse.matcher/effect`
- **THEN** the runtime SHALL normalize that declaration into the canonical registration schema before validating phase eligibility, effect-field eligibility, scope, and ownership

#### Scenario: legacy agent-owned hooks require explicit legacy enablement
- **WHEN** an agent definition uses a legacy phase-keyed `hooks` mapping without explicit legacy compatibility enablement
- **THEN** the runtime SHALL reject or deactivate that declaration instead of treating it as an ordinary public v1 authoring surface
- **AND** the runtime SHALL surface the canonical migration targets through diagnostics or equivalent metadata

#### Scenario: runtime config and turn API preserve the same normalized fields
- **WHEN** a runtime configuration document and a turn-scoped programmatic registration both target the same public phase
- **THEN** the runtime SHALL preserve the same normalized fields for phase, matcher, scope, owner attribution, handler manifest, and declared effect contract even if their authoring envelopes differ

#### Scenario: declarative callback hooks use binding identifiers rather than serialized code
- **WHEN** a declarative authoring surface such as runtime config or frontmatter targets a `callback` hook handler
- **THEN** that surface SHALL reference a stable host-provided callback binding identifier rather than embedding executable code or raw callable state in the document
