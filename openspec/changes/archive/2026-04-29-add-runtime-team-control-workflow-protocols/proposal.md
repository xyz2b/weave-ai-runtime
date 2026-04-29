## Why

The runtime already has durable team membership, control-message envelopes, and correlated message IDs, but it still lacks runtime-owned workflow semantics for "must-negotiate" team actions. Today teammate permission requests still fall through to the host approval path directly, and teammate shutdown on removal or team deletion still resolves as immediate runner teardown instead of a graceful request/acknowledgement flow.

This gap matters now because the next collaboration steps depend on it. Autonomous teammate pickup and idle shutdown need a safe stop protocol, and leader-mediated approval only becomes real when the leader can issue a typed decision instead of receiving a replay-only notification.

Recent source study of Claude Code reinforces both the opportunity and the constraint here. Its multi-agent runtime already demonstrates that a shared request/response plus unique-ID pattern works well for permission and shutdown coordination, that protocol constructors/parsers benefit from being centralized, and that leader approvals integrate more cleanly when they can reuse existing decision surfaces instead of fabricating raw transport messages. The same study also shows the failure mode we want to avoid: once workflow state lives only in mailbox traffic, "approval" degrades into an observational notification or default auto-approval path rather than a runtime-owned authority boundary.

## What Changes

- Introduce a runtime-owned team control workflow protocol for correlated request/response interactions such as approval and shutdown, with stable workflow identity, terminal decisions, timeout handling, and recovery-safe state.
- Consolidate approval and shutdown around a shared request/response plus stable-ID protocol shape, with centralized typed schema helpers so future negotiated control actions can reuse the same control-plane contract instead of inventing ad hoc message formats.
- Upgrade teammate permission mediation so teammate-originated privileged steps enter an explicit leader-mediated approval workflow before any required host permission resolution is finalized.
- Add a graceful teammate shutdown workflow for member removal, team deletion, and explicit stop requests, including `stopping` and `stopped` lifecycle semantics plus acknowledgement or completion signaling before teardown.
- Add typed decision surfaces that preferentially reuse existing runtime or host decision pathways so leader sessions and bound hosts can approve, reject, acknowledge, or otherwise resolve pending team control workflows without fabricating raw control messages or depending on a parallel UI-only path.
- Extend leader-side ingress and workflow observability so actionable control requests can be surfaced as ordered runtime inputs or private control-plane updates while preserving correlation metadata and transcript-hiding defaults for private control traffic.
- Add explicit prioritization and observability rules for team control workflows so high-priority actions such as shutdown requests are not starved behind lower-priority teammate chatter, while still keeping raw protocol envelopes private by default.
- Add regression coverage for correlated workflow delivery, decision routing, graceful shutdown cleanup, timeout or recovery behavior, and unchanged mailbox correctness invariants.

## Capabilities

### New Capabilities
- `runtime-team-control-workflows`: Correlated request/response workflows for team-scoped approval, shutdown, and similar negotiated control actions, including workflow identity, decision routing, lifecycle, timeout, and recovery semantics.

### Modified Capabilities
- `teammate-orchestration`: Permission bridging and teammate lifecycle requirements change so negotiated approval and graceful stop flows become authoritative instead of direct host approval or immediate teardown.
- `runtime-session-ingress`: Leader-directed team control workflows change ingress behavior by allowing actionable workflow requests to surface through runtime-owned ingress outcomes in addition to replay-only or private control handling.
- `host-runtime-bridge`: Host-facing team integration changes to expose pending workflow observation and typed decision submission for approval and shutdown resolution.
- `builtin-runtime-pack`: The bundled runtime tool surface changes to expose explicit leader-side workflow decision operations rather than relying on raw messaging for approval or shutdown responses.

## Impact

- Affected code: `src/runtime/team_message_bus.py`, `src/runtime/team_control_plane.py`, `src/runtime/teammate_orchestration/service.py`, `src/runtime/teammate_orchestration/models.py`, `src/runtime/session_runtime/ingress.py`, `src/runtime/session_runtime/controller.py`, `src/runtime/builtins/tools.py`, `src/runtime/builtins/tool_impls.py`, `src/runtime/runtime_kernel/kernel.py`, and `src/runtime/hosts/base.py`.
- New code: workflow-state models or stores for pending control requests, centralized protocol-schema helpers, leader or host decision adapters, graceful stop coordination helpers, control-workflow prioritization or observability glue, and test coverage for workflow recovery and teardown ordering.
- Public/runtime contract: new team-control workflow semantics, new leader or host decision surfaces, and stricter teammate shutdown behavior before runtime-owned cleanup.
- Dependency note: this change assumes the current runtime team control plane and persistent teammate orchestration remain the baseline collaboration substrate; it refines their control semantics rather than replacing them.
