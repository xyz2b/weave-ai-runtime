## Why

The runtime already has formal package protocols for manifests, contributions, capability lookup, host facets, and lifecycle participation, but `runtime-core` owner layers still retain package-specific seams for team workflow replay, delivery acknowledgements, compatibility slots, and host helpers. As package-oriented runtime features grow, those leaks make it too easy for new package behavior to widen `SessionController`, `BoundHostRuntime`, `RuntimeAssembly`, or `RuntimeServices` instead of attaching through the published protocol surfaces.

Now is the right time to tighten those seams. The package protocol model is mature enough to become the only normative attachment path for first-party package behavior, but the framework is not yet at the point where a purity rewrite, flag-day compatibility removal, or open-ended third-party plugin system would pay back the churn.

## What Changes

- Define a protocol-only owner-layer boundary for `runtime-core`: package-owned behavior SHALL attach through capability lookup, host facet lookup, lifecycle participants, and bounded ingress receipts rather than through new package-specific owner-layer special cases.
- Move package-owned session-open replay off `SessionController` special cases and onto lifecycle participants, while preserving `SessionController` as the owner of session start/resume semantics.
- Extend the formal session-ingress contract with named `IngressCompletionReceipt` semantics on `SessionIngressResult` so package-owned post-ingress acknowledgements stop depending on ad hoc metadata keys such as package-specific delivery acks.
- Reclassify package-specific runtime and host helpers as compatibility wrappers over capability and host-facet discovery rather than as canonical extension APIs.
- Continue staged compatibility cleanup for team-specific top-level slots and `TaskManager`-shaped runtime paths without requiring a flag-day removal of those compatibility layers.
- Explicitly defer broader third-party package registration, generalized package event buses, and purity-driven microkernel refactors until the first-party owner-layer seams are fully tightened.

## Capabilities

### New Capabilities
- `runtime-package-owner-layer-boundaries`: Defines the normative rule that `runtime-core` owner layers consume package extensions only through runtime-owned protocol seams, with compatibility wrappers treated as non-canonical projections.

### Modified Capabilities
- `host-runtime-bridge`: Optional package-owned host helpers and sinks become canonical only through host-facet discovery, while package-specific host methods remain bounded compatibility surfaces.
- `runtime-control-plane-spine`: Shared runtime control-plane surfaces consume package-owned services and replay participants through capability and lifecycle protocols instead of package-specific top-level service slots.
- `runtime-session-ingress`: Ingress results gain `SessionIngressResult.completion_receipts` with bounded `IngressCompletionReceipt` semantics for post-ingress acknowledgements without widening the controller with package-specific metadata handling.
- `runtime-lifecycle-ownership`: Package-owned session-open replay behavior executes inside runtime-owned lifecycle phases while session and host ownership stay with the core lifecycle managers.

## Impact

- Affected code:
  - `src/runtime/session_runtime/controller.py`
  - `src/runtime/session_runtime/ingress.py`
  - `src/runtime/session_runtime/models.py`
  - `src/runtime/runtime_services/__init__.py`
  - `src/runtime/runtime_kernel/kernel.py`
  - `src/runtime/hosts/base.py`
  - `src/runtime/runtime_package_protocols.py`
  - `src/runtime/runtime_package_manifests.py`
  - `src/runtime/team_message_bus.py`
  - `src/runtime/team_control_plane.py`
  - `src/runtime/team_workflows.py`
  - `src/runtime/builtins/tool_impls.py`
- Affected APIs and contracts:
  - session-ingress result structure
  - `SessionIngressResult.completion_receipts`
  - lifecycle-participant usage at session-open boundaries
  - capability and host-facet discovery as canonical package lookup paths
  - compatibility wrappers for team workflow operations and package-specific host/runtime helpers
- Related systems:
  - runtime package protocol integration
  - team control/workflow delivery
  - host bridge integration
  - task/job compatibility cleanup
