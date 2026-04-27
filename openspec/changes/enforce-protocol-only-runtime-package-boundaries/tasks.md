## 1. Protocol Scaffolding

- [ ] 1.1 Extend session-ingress models with `IngressCompletionReceipt` and `SessionIngressResult.completion_receipts`.
- [ ] 1.2 Preserve ingress-emitted receipt descriptors, ordering, and `kind`/`receipt_id` identity through ingress processing and result construction.
- [ ] 1.3 Add or formalize the runtime-owned receipt execution path so session control can process post-ingress acknowledgements without package-specific branches.
- [ ] 1.4 Add regression coverage for ingress receipt ordering across transcript, replay, and private-state updates, including fail-stop failure surfacing after commit.

## 2. Migrate Package-Owned Session Replay

- [ ] 2.1 Register `runtime-team` session-open replay through `SESSION_OPEN` lifecycle participant wiring.
- [ ] 2.2 Move start/resume replay ordering to the lifecycle-driven path while preserving `SessionController` ownership of ready transition and waiting-session follow-up.
- [ ] 2.3 Remove controller-owned team replay special cases once the lifecycle path is authoritative.
- [ ] 2.4 Rework team delivery acknowledgement flow to use ingress completion receipts instead of controller-owned `team_delivery_ack` handling.
- [ ] 2.5 Preserve waiting-session drain, replay, and resume behavior with focused team-mode and session-runtime tests.

## 3. Canonical Lookup and Compatibility Wrappers

- [ ] 3.1 Refactor kernel-owned workflow operations to resolve package-owned behavior through host facets and capability lookup first.
- [ ] 3.2 Refactor bound-host workflow helper paths to proxy through the same canonical lookup semantics instead of direct package-owned assumptions.
- [ ] 3.3 Demote top-level team slots and helper methods to explicit compatibility wrappers over canonical lookup paths, without leaving unique behavior on the wrappers.
- [ ] 3.4 Update runtime metadata, migration notes, and integration docs to label package-specific helpers as compatibility-only, lookup paths as canonical, and wrapper exit criteria as staged follow-up work.

## 4. Host Bridge and Control-Plane Cleanup

- [ ] 4.1 Freeze package-specific host event sink semantics and prevent new mandatory host-bridge package methods from being introduced in this path.
- [ ] 4.2 Narrow runtime-owned primary paths that still create or depend on authoritative `TaskManager`-shaped state.
- [ ] 4.3 Keep only the minimum required legacy `TaskManager` fallbacks, with explicit compatibility labeling where they remain.
- [ ] 4.4 Add regression coverage proving capability/facet lookup remains authoritative while compatibility wrappers continue to proxy equivalent behavior.
