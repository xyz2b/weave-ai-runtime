## ADDED Requirements

### Requirement: Permission decisions are unified in a runtime permission engine
The runtime SHALL use a unified permission engine to evaluate tool, skill, and delegated execution requests by combining tool-level permission checks, hook effects, session permission context, and host approval.

#### Scenario: Tool requires approval
- **WHEN** a tool execution request results in an ask-style permission outcome after runtime policy evaluation
- **THEN** the runtime SHALL route the approval request through the shared permission engine instead of relying on a tool-local prompt path

### Requirement: Session permission context is explicit
The runtime SHALL maintain an explicit session permission context that includes permission mode and persistent allow, deny, or ask rules.

#### Scenario: Background execution avoids interactive prompts
- **WHEN** a session or delegated execution context is configured to avoid permission prompts
- **THEN** the permission engine SHALL apply that session permission context when deciding whether to deny, allow, or escalate the request

### Requirement: Elicitation requests use a shared runtime service
The runtime SHALL provide a shared elicitation service for `ask_user`-style requests, structured follow-up prompts, and hook-satisfied elicitation responses.

#### Scenario: Hook satisfies an elicitation request
- **WHEN** an elicitation-capable phase or tool request is resolved directly by a registered hook
- **THEN** the runtime SHALL return the hook-provided elicitation result through the shared elicitation service without requiring host interaction

#### Scenario: Host provides elicitation response
- **WHEN** the runtime cannot resolve an elicitation request from hooks or defaults
- **THEN** the runtime SHALL route that request to the host through the shared elicitation service and resume the waiting execution path with the returned response

### Requirement: Tool and skill execution share the same permission and elicitation control plane
The runtime SHALL apply the same permission and elicitation control-plane behavior to tool execution, skill execution, and delegated agent execution paths.

#### Scenario: Skill invocation requires permission
- **WHEN** a skill invocation carries permission-relevant traits such as restricted tools, forked execution, or hook registration
- **THEN** the runtime SHALL evaluate that invocation through the shared permission and elicitation control plane instead of a skill-specific ad hoc path
