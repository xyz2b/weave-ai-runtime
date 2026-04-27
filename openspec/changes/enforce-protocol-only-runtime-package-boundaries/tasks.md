## 1. Protocol Scaffolding

- [x] 1.1 Extend session-ingress models with `IngressCompletionReceipt` and `SessionIngressResult.completion_receipts`.
- [x] 1.2 Preserve ingress-emitted receipt descriptors, ordering, and `kind`/`receipt_id` identity through ingress processing and result construction.
- [x] 1.3 Add or formalize the runtime-owned receipt execution path so session control can process post-ingress acknowledgements without package-specific branches.
- [x] 1.4 Add regression coverage for ingress receipt ordering across transcript, replay, and private-state updates, including fail-stop failure surfacing after commit.

## 2. Migrate Package-Owned Session Replay

- [x] 2.1 Register `runtime-team` session-open replay through `SESSION_OPEN` lifecycle participant wiring.
- [x] 2.2 Move start/resume replay ordering to the lifecycle-driven path while preserving `SessionController` ownership of ready transition and waiting-session follow-up.
- [x] 2.3 Remove controller-owned team replay special cases once the lifecycle path is authoritative.
- [x] 2.4 Rework team delivery acknowledgement flow to use ingress completion receipts instead of controller-owned `team_delivery_ack` handling.
- [x] 2.5 Preserve waiting-session drain, replay, and resume behavior with focused team-mode and session-runtime tests.

## 3. Canonical Lookup and Compatibility Wrappers

- [x] 3.1 Refactor kernel-owned workflow operations to resolve package-owned behavior through host facets and capability lookup first.
- [x] 3.2 Refactor bound-host workflow helper paths to proxy through the same canonical lookup semantics instead of direct package-owned assumptions.
- [x] 3.3 Demote top-level team slots and helper methods to explicit compatibility wrappers over canonical lookup paths, without leaving unique behavior on the wrappers.
- [x] 3.4 Update runtime metadata, migration notes, and integration docs to label package-specific helpers as compatibility-only, lookup paths as canonical, and wrapper exit criteria as staged follow-up work.

## 4. Host Bridge and Control-Plane Cleanup

- [x] 4.1 Freeze package-specific host event sink semantics and prevent new mandatory host-bridge package methods from being introduced in this path.
- [x] 4.2 Narrow runtime-owned primary paths that still create or depend on authoritative `TaskManager`-shaped state.
- [x] 4.3 Keep only the minimum required legacy `TaskManager` fallbacks, with explicit compatibility labeling where they remain.
- [x] 4.4 Add regression coverage proving capability/facet lookup remains authoritative while compatibility wrappers continue to proxy equivalent behavior.
