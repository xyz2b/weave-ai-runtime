## ADDED Requirements

### Requirement: Completion receipts SHALL use an explicit ingress-owned descriptor
The ingress protocol SHALL represent post-ingress acknowledgements as `IngressCompletionReceipt` descriptors carried on `SessionIngressResult.completion_receipts`, rather than as ad hoc metadata keys or controller-owned package branches.

#### Scenario: ingress publishes a completion receipt
- **WHEN** an ingress result needs to expose post-ingress acknowledgement work
- **THEN** it SHALL publish an `IngressCompletionReceipt` on `SessionIngressResult.completion_receipts`
- **AND** that descriptor SHALL include a stable `receipt_id` and a named `kind`
- **AND** any receipt payload consumed by the runtime-owned executor SHALL remain opaque to `SessionController`

### Requirement: Ingress results SHALL expose bounded completion receipts for post-ingress acknowledgements
The ingress pipeline SHALL allow a structured ingress result to carry bounded completion receipts that session control can execute after ingress-defined transcript, replay, and private-state effects have been committed.

#### Scenario: ingress requires a post-ingress acknowledgement
- **WHEN** an inbound event requires a deterministic acknowledgement or receipt after ingress effects are committed
- **THEN** the ingress result SHALL expose that acknowledgement through a bounded completion-receipt protocol
- **AND** it SHALL NOT require the session controller to infer that acknowledgement solely from package-specific metadata keys inside normalized messages or private updates

### Requirement: Session control SHALL execute completion receipts without package-specific ingress branches
The session controller SHALL execute ingress completion receipts through the shared ingress protocol rather than through package-specific acknowledgement helper branches.

#### Scenario: package-owned delivery acknowledgement completes after ingress execution
- **WHEN** a package-owned inbound flow requires a delivery acknowledgement after transcript, replay, or private-state effects are applied
- **THEN** the session controller SHALL execute the bounded completion receipt emitted by ingress
- **AND** it SHALL preserve session-owned ingress ordering without introducing a package-specific acknowledgement path in session control

### Requirement: Completion receipts SHALL execute in bounded post-commit order
The ingress protocol SHALL require completion receipts to execute only after ingress-defined transcript, replay, and private-state effects commit, and the session controller SHALL preserve the emitted receipt order.

#### Scenario: ingress emits multiple completion receipts
- **WHEN** an ingress result carries more than one completion receipt
- **THEN** the session controller SHALL execute those receipts in emitted order after ingress effects commit
- **AND** it SHALL NOT execute a later receipt before an earlier receipt has completed or failed

#### Scenario: completion receipt fails after ingress effects commit
- **WHEN** a completion receipt fails after transcript, replay, or private-state effects have already been applied
- **THEN** the runtime SHALL surface that failure through a runtime-owned outcome or diagnostics path
- **AND** it SHALL NOT require the session controller to infer or perform package-specific rollback logic for the already-committed ingress effects

### Requirement: Receipt execution failure SHALL be fail-stop for the active receipt sequence
The session controller SHALL stop executing later receipts from the same ingress result after the first receipt failure in that execution attempt.

#### Scenario: earlier receipt fails while later receipts remain pending
- **WHEN** one completion receipt fails and later receipts from the same ingress result have not yet run
- **THEN** the session controller SHALL stop the active receipt sequence at the failed receipt
- **AND** it SHALL surface the failure through the runtime-owned receipt outcome path
- **AND** it SHALL NOT treat the already-committed ingress effects as rolled back
