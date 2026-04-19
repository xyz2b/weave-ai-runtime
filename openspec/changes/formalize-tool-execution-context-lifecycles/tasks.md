## 1. Scope and context primitives

- [ ] 1.1 Define explicit `SessionScope`, `TurnScope`, `InternalToolContext`, and `ToolExecutionContext` data shapes and align naming with their intended visibility.
- [ ] 1.2 Introduce explicit `SessionStateHandle` and `TurnStateHandle` public interfaces in place of the current ambiguous single `app_state` concept.
- [ ] 1.3 Update tool lifecycle and query context carriers so call-scoped execution context freezes call identity while reusing owner-provided scope handles.
- [ ] 1.4 Define explicit tool trust classification metadata and default routing rules for public, privileged, and legacy-compat execution paths.
- [ ] 1.5 Define a narrow read-only projection for any runtime-private execution metadata that must reach public tools, rather than exposing the raw private carrier.

## 2. Ownership and execution path wiring

- [ ] 2.1 Refactor `SessionController` to create and own `SessionScope` and to provide session-scoped resources explicitly rather than through implicit tool-context defaults.
- [ ] 2.2 Refactor `TurnEngine` to create and own `TurnScope`, including turn-scoped file state, progress, notifications, capability refresh, and abort handles.
- [ ] 2.3 Update tool resolution and execution paths to derive public `ToolExecutionContext` from the active turn scope while keeping `InternalToolContext` on the internal runtime path.
- [ ] 2.4 Reserve an optional session-owned internal cache slot on `SessionScope`; do not block the first migration stage on implementing a concrete read-cache backend.

## 3. Compatibility and privileged tool handling

- [ ] 3.1 Add a compatibility adapter for legacy tools that still expect the current mixed `ToolContext` shape.
- [ ] 3.2 Restrict raw `runtime_services`, registries, and privileged runners to the internal tool path and remove them from the public tool execution ABI.
- [ ] 3.3 Classify privileged built-in tools that still require internal control-plane access and route them through an internal adapter without widening the public ABI.
- [ ] 3.4 Document and enforce exit criteria for the legacy compatibility path so new non-runtime-owned tools default to the public execution path.
- [ ] 3.5 Make runtime-owned registration or assembly data authoritative for privileged and legacy-compat routing; treat tool self-description as non-authoritative input only.

## 4. Validation and conformance

- [ ] 4.1 Add tests that verify session-scoped resources persist across turns while turn-scoped resources reset at terminal turn completion.
- [ ] 4.2 Add tests that verify public tool execution receives only the narrowed `ToolExecutionContext` capability surface and not raw internal runtime services.
- [ ] 4.3 Add compatibility tests that verify legacy tools and privileged built-in tools continue to execute during the migration.
- [ ] 4.4 Add tests that verify non-runtime-owned tools default to the public path, privileged tools use explicit internal routing, and compat paths do not widen the public ABI.
