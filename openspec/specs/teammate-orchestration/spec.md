# teammate-orchestration Specification

## Purpose
TBD - created by archiving change add-persistent-teammate-orchestration. Update Purpose after archive.
## Requirements
### Requirement: Teammate work SHALL reuse the shared execution core
runtime SHALL route teammate work through the existing shared agent execution path instead of introducing a separate execution engine for teammate orchestration.

#### Scenario: teammate consumes a mailbox work item
- **WHEN** a teammate claims a mailbox item that requires model execution
- **THEN** runtime SHALL convert that work item into a structured execution request
- **AND** SHALL execute it through the shared agent execution service
- **AND** SHALL continue to reuse the shared turn execution path for the child run

### Requirement: Teammate mailbox SHALL be file-backed
runtime SHALL implement teammate mailbox storage with filesystem-backed message files, organized around per-teammate mailbox state directories, not an in-memory-only queue.

#### Scenario: leader publishes a mailbox message
- **WHEN** the leader sends a work item or control message to a teammate
- **THEN** runtime SHALL persist the message as a mailbox file before marking it visible to the receiver
- **AND** SHALL publish it with an atomic handoff mechanism so readers never observe a partially written envelope

#### Scenario: multiple writers target the same teammate inbox
- **WHEN** more than one writer publishes messages to the same teammate inbox concurrently
- **THEN** runtime SHALL use a claim or lock mechanism that prevents envelope corruption and duplicate consumption
- **AND** SHALL preserve enough metadata for the receiver to recover unread messages after process restart

#### Scenario: a teammate claims and completes a mailbox item
- **WHEN** a teammate successfully claims a mailbox envelope from its inbox
- **THEN** runtime SHALL move that envelope into a claimed state with exclusive consumer metadata
- **AND** SHALL assign or attach the execution linkage needed to correlate the resulting run
- **AND** SHALL eventually move the envelope into exactly one terminal state bucket representing done, failed, or retry

#### Scenario: runtime recovers stale claimed work after restart
- **WHEN** runtime restarts and finds a claimed mailbox envelope without a live claimer, active run linkage, or active permission wait
- **THEN** runtime SHALL treat that claim as stale
- **AND** SHALL requeue or retry the envelope without duplicating a terminally archived message

#### Scenario: retry attempts exceed the configured ceiling
- **WHEN** a mailbox envelope reaches or exceeds the configured automatic retry ceiling
- **THEN** runtime SHALL move that envelope into a terminal failed state instead of requeueing it again
- **AND** SHALL preserve the final attempt count and retry reason in terminal metadata or the terminal envelope record

### Requirement: Teammate identity SHALL be persistent and task-independent
runtime SHALL assign each teammate a stable identity that survives across multiple work items, and SHALL NOT treat a task identifier as the authoritative teammate identity.

#### Scenario: one teammate handles multiple work items over time
- **WHEN** the same teammate finishes one mailbox item and later picks up another
- **THEN** runtime SHALL keep the same teammate identity across both executions
- **AND** SHALL allow run identifiers and projected task identifiers to change independently per execution

#### Scenario: an in-process teammate is hosted by a task
- **WHEN** an in-process teammate is currently represented by a host-visible task
- **THEN** runtime SHALL treat that task as a projection of the teammate's current execution slot
- **AND** SHALL NOT redefine the teammate's identity from the task identifier

### Requirement: Permission requests SHALL flow through a leader-mediated bridge
runtime SHALL route teammate permission requests through a leader-mediated permission bridge instead of allowing each teammate to negotiate host permissions directly.

#### Scenario: a teammate needs approval for a privileged action
- **WHEN** a teammate reaches a step that requires approval or elevated permission
- **THEN** runtime SHALL forward a correlated permission request to the leader-side bridge
- **AND** SHALL keep the teammate in a waiting state until the bridge returns a decision
- **AND** SHALL NOT grant the permission through a direct teammate-to-host path

### Requirement: Teammates SHALL expose an idle lifecycle independent of task lifetime
runtime SHALL model teammate lifecycle with explicit availability states including `starting`, `idle`, `active`, `waiting_permission`, `stopping`, and `stopped`, and SHALL allow a teammate to remain addressable after a projected task has ended.

#### Scenario: a teammate drains its queue
- **WHEN** a teammate completes its current execution and no mailbox items remain
- **THEN** runtime SHALL transition that teammate to an idle or available state
- **AND** SHALL allow later mailbox messages to reactivate the same teammate identity

#### Scenario: a projected task closes while the teammate remains available
- **WHEN** the host-visible task for a completed run is closed
- **THEN** runtime SHALL keep the teammate registered as addressable until it is explicitly stopped
- **AND** SHALL NOT require a new teammate identity for the next mailbox item

#### Scenario: a teammate waits for permission and then resumes
- **WHEN** a teammate enters `waiting_permission` because a privileged step requires approval
- **THEN** runtime SHALL preserve the teammate identity, current message linkage, and permission correlation while waiting
- **AND** SHALL resume the same teammate from `waiting_permission` to `active` only after the bridge returns an approval decision

#### Scenario: lifecycle state is persisted for recovery
- **WHEN** a teammate changes lifecycle state or changes its current message, claim, run, or permission linkage
- **THEN** runtime SHALL persist a recovery-oriented state snapshot for that teammate
- **AND** SHALL keep the persisted state consistent with the teammate's latest lifecycle state and current linkage fields

### Requirement: Task and progress surfaces SHALL be projections of teammate state
runtime SHALL derive host-visible task, progress, and notification surfaces from teammate state and current execution, rather than making those surfaces the primary source of truth.

#### Scenario: a teammate begins processing a mailbox item
- **WHEN** a teammate transitions from idle to active because it claimed a mailbox item
- **THEN** runtime SHALL create or update the corresponding task and progress projection from teammate state plus current run metadata
- **AND** SHALL preserve the teammate identity even if the projected task is later replaced or closed

#### Scenario: a teammate emits completion or idle notifications
- **WHEN** a teammate finishes a run or returns to idle
- **THEN** runtime SHALL emit notifications derived from the teammate lifecycle transition
- **AND** SHALL keep notification state consistent with the teammate's recorded lifecycle and current run status

