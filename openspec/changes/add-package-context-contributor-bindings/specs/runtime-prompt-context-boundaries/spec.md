## MODIFIED Requirements

### Requirement: Control-plane services contribute prompt and private data independently
The runtime SHALL support control-plane contributors, including package-contributed context participants, that can independently add prompt-visible fragments and runtime-private updates during request preparation.

#### Scenario: Memory service contributes prompt and retrieval trace separately
- **WHEN** memory retrieval produces both model guidance and retrieval diagnostics
- **THEN** the runtime SHALL carry model guidance through the prompt-visible channel and retrieval diagnostics through the runtime-private channel

#### Scenario: Package contributor adds private-only diagnostics
- **WHEN** a package-contributed context participant produces execution diagnostics or runtime hints that are not model-facing
- **THEN** the runtime SHALL merge those updates into runtime-private context without automatically exposing them in prompt text

#### Scenario: Package contributor adds prompt-visible guidance
- **WHEN** a package-contributed context participant emits prompt-visible guidance for the next request
- **THEN** the runtime SHALL merge that guidance through the same prompt-visible carrier used by built-in control-plane contributors
- **AND** SHALL preserve the documented prompt/private separation for the rest of the request path
