## Why

The runtime already has persistent teammate execution primitives, but it does not yet expose a full team control plane that lets a lead agent create teammates, keep them alive across multiple tasks, route structured teammate messages, and coordinate permission or shutdown flows through runtime-owned contracts. That makes multi-agent collaboration possible only through low-level orchestration APIs instead of through a first-class framework surface.

This gap matters now because the framework is explicitly runtime-first and headless: it needs stable control-plane interfaces that product teams and hosts can build UI on top of, rather than baking Claude Code-specific UI behavior into the core. The next step is to formalize team state, teammate communication, and leader routing as runtime capabilities.

## What Changes

- Introduce a runtime-owned team control plane that manages team identity, leader membership, teammate membership, team-scoped private context, lifecycle, and cleanup independently from any specific UI implementation.
- Add a structured team message bus for direct, broadcast, and control-plane messages between leader and teammates, including protocol messages for permission mediation, shutdown, and runtime-directed mode changes.
- Add first-party built-in team tools so the lead agent can create a team, spawn teammates, send teammate messages, and delete or shut down the team through stable runtime contracts.
- Add a runtime-owned leader inbox routing path that converts teammate messages and control messages into session ingress events, private updates, notifications, or host callbacks instead of hard-coded UI state mutation.
- Keep `PersistentTeammateOrchestrator` as the execution substrate for teammate work items, but layer the team/session/message control plane above it instead of overloading the existing work-queue mailbox with all collaboration semantics.
- Expose host-facing, headless integration surfaces for team lifecycle, team message delivery, permission approvals, and teammate shutdown handling so framework users can implement their own UI or automation on top.

## Capabilities

### New Capabilities
- `runtime-team-control-plane`: A runtime-owned team registry and lifecycle model for creating teams, attaching a leader session, spawning and cleaning up teammates, and maintaining team-scoped control-plane state without depending on bundled UI.
- `runtime-team-message-bus`: A structured, headless communication and control protocol for leader-to-teammate and teammate-to-teammate messaging, including routing for direct messages, broadcasts, permission requests/responses, shutdown requests, and other team control messages.

### Modified Capabilities
- `builtin-runtime-pack`: Built-in tooling expands to include first-party team control tools and the corresponding input/output contracts for headless team creation, teammate spawning, messaging, and deletion.
- `host-runtime-bridge`: Hosts gain explicit runtime-owned integration surfaces for observing team lifecycle, consuming team notifications or control callbacks, and supplying approvals or policy decisions without the runtime taking ownership of UI state.
- `runtime-session-ingress`: Leader-side teammate messages and team control events can enter a session through structured ingress outcomes rather than only as raw transcript text or ad hoc notifications.

## Impact

- Affected code: `src/runtime/builtins/tools.py`, `src/runtime/builtins/tool_impls.py`, `src/runtime/runtime_services/__init__.py`, `src/runtime/runtime_kernel/kernel.py`, `src/runtime/session_runtime/controller.py`, `src/runtime/session_runtime/ingress.py`, `src/runtime/hosts/base.py`, and `src/runtime/teammate_orchestration/service.py`.
- New code: runtime team registry/state modules, team message bus modules, leader inbox router or coordinator services, teammate runner management, host bridge extension types, and tests covering team lifecycle and message routing.
- Public/runtime contract: new built-in `team_*` tools, new headless host integration points, and new team-scoped session/private-context semantics.
- Non-goal: this change does not bundle a UI, terminal pane manager, or frontend state model; framework consumers remain responsible for rendering teammate state and interaction surfaces.
