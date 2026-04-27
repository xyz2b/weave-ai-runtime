## ADDED Requirements

### Requirement: Runtime assembly registers invocation providers from package contributions and config
The runtime SHALL assemble the shared invocation registry from the built-in skill provider baseline, package-contributed invocation providers, and config-supplied providers before exposing runnable host or session surfaces.

#### Scenario: assembled runtime exposes package-owned invocation source
- **WHEN** a runtime package contributes an invocation provider and the runtime finishes assembly
- **THEN** the assembled runtime SHALL expose that provider through the same invocation-registry-backed catalog surfaces used for skills
- **AND** hosts SHALL be able to resolve visible invocations without re-registering that provider manually
