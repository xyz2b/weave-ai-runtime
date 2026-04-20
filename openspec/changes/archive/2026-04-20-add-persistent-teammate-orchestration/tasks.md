## 1. Core Contracts

- [x] 1.1 Define the teammate orchestration shell boundary above the shared agent execution service
- [x] 1.2 Introduce the teammate registry, lifecycle state model, and recovery-oriented `state.json` contract
- [x] 1.3 Add configuration or feature-gate surfaces for enabling persistent teammate orchestration

## 2. File Mailbox Runtime

- [x] 2.1 Implement the file-backed mailbox directory layout and envelope schema with atomic publish semantics
- [x] 2.2 Add claim, lease, heartbeat, and terminal-state transitions for mailbox items
- [x] 2.3 Implement restart recovery, stale-claim handling, and retry ceiling behavior for unread or interrupted mailbox items

## 3. Execution And Permission Bridging

- [x] 3.1 Implement the handoff from claimed mailbox work items to structured execution requests on the shared execution core
- [x] 3.2 Route teammate approval and permission requests through a leader-mediated bridge
- [x] 3.3 Keep teammate lifecycle, current linkage fields, and permission wait state consistent across execution pauses and resumes

## 4. Projection And Verification

- [x] 4.1 Derive host-visible task, progress, and notification projections from teammate state and current run metadata
- [x] 4.2 Add tests for mailbox atomicity, duplicate-consume protection, stale-claim recovery, and retry ceilings
- [x] 4.3 Add tests for stable teammate identity, permission bridge routing, idle reactivation, and projection-state consistency
