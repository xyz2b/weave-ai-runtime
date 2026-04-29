## ADDED Requirements

### Requirement: Parent-facing child projection stays separate from sidechain truth

The runtime SHALL preserve a separation between parent-facing child result projection and child sidechain observability so parent context hygiene does not weaken child-run truth surfaces.

#### Scenario: Summary-first parent result does not erase child history

- **WHEN** a parent-facing child result is emitted under the default summary-first policy
- **THEN** the runtime SHALL keep the child's full internal message history in child sidechain storage or equivalent child-run records
- **AND** SHALL NOT require the parent-facing projection to duplicate that full history

#### Scenario: Child history remains queryable by child identity

- **WHEN** a caller inspects a child run whose parent received only a summary projection
- **THEN** the runtime SHALL still expose the child run record and child message history through child-run observability surfaces
- **AND** SHALL preserve the linkage needed to associate that child record with its parent execution

#### Scenario: Host observability retains full child-run truth

- **WHEN** the parent-facing child result is summary-only by default
- **THEN** host-visible child-run observability such as `CHILD_RUN` lifecycle events SHALL still align with the full child sidechain record
- **AND** SHALL NOT be reduced to the parent-facing summary projection contract
