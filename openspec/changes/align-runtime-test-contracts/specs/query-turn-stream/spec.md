## MODIFIED Requirements

### Requirement: Terminal turn metadata is surfaced explicitly
The runtime SHALL surface terminal metadata for each provider attempt and completed turn, including stop reason, request and abort identifiers, provider usage details when available, and additive runtime metadata produced by the control plane or provider adapter.

#### Scenario: Turn completes with terminal metadata
- **WHEN** a provider response reaches message stop or an explicit terminal error state
- **THEN** the runtime SHALL expose stop reason and available usage/request metadata through the turn result contract
- **AND** it SHALL preserve additive terminal metadata instead of reducing the payload to a fixed minimal dictionary

#### Scenario: Interrupted turn preserves abort and runtime metadata
- **WHEN** a turn is interrupted after terminal metadata has already been partially observed
- **THEN** the runtime SHALL emit terminal metadata that includes the stable interrupt fields such as `stop_reason`, `request_id`, and `abort_reason`
- **AND** it SHALL preserve any additive runtime metadata that remains attached to the terminal event
