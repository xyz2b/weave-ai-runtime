## Recommended implementation order

- Phase A - closure report spine: land `1.1`, `1.2`, `2.1`, `4.1`, and `4.2` together first so every later retirement/hardening change writes to one canonical metadata and inspection surface.
- Phase B - compatibility gating: land `1.3`, `1.4`, and `1.5` next so the default primary path actually stops silently re-promoting legacy surfaces.
- Phase C - persistence productization: land `2.2` and `2.3` after the closure-report spine exists so `runtime-full` can publish the first production-oriented persistence contract immediately.
- Phase D - isolation hardening: land `3.1` and `3.2` after the report/gating foundation so `worktree` and `remote` readiness can publish honest lease state rather than more transitional metadata.
- Phase E - regression and conformance gates: land `1.6`, `1.7`, `2.4`, `2.5`, `3.3`, `4.3`, and `4.4` only after the core compatibility/persistence/isolation behaviors settle, so the matrix locks the final contract instead of chasing churn.
- Phase F - docs and migration closeout: land `5.1`, `5.2`, and `5.3` last, once contract names, closure-report fields, and migration targets are stable.

## Recommended first slice

- Start with `1.1` + `2.1` + `4.1` + `4.2`: define the closure-report schema, publish it in runtime assembly metadata, and expose inspection helpers before changing behavior.
- Add `1.2` in the same slice or immediately after: the compatibility-retirement inventory is the source of truth that the later gating and closure-green checks depend on.
- Do not start with `3.x` or `2.2` first: those implementations are easier to finish once the runtime already has a canonical place to publish readiness/durability state.

## 1. Compatibility retirement contract

- [ ] 1.1 Add runtime-owned compatibility-retirement models and publish a canonical closure report at `runtime.services.metadata["closure_report"]` / `runtime.metadata["closure_report"]`.
- [ ] 1.2 Audit every currently documented compatibility surface and encode the complete retirement inventory, migration target, and family-level activation state in the closure report.
- [ ] 1.3 Introduce explicit per-family legacy-mode controls for the remaining compatibility families instead of leaving those paths silently enabled by default.
- [ ] 1.4 Narrow default public/runtime-owned access to `TaskManager`, shared authoritative `runtime_context` writes, and package-specific compatibility projections so they cannot re-emerge as canonical lookup paths.
- [ ] 1.5 Tighten agent-owned legacy hook authoring so it is rejected or legacy-gated by default, while preserving supported legacy skill/invocation hook normalization and other supported hook migration paths.
- [ ] 1.6 Add regression tests that assert each documented compatibility family appears in the retirement inventory, that authoritative legacy coordination writes fail outside legacy mode, and that legacy-enabled families keep the assembly out of closure-green status.
- [ ] 1.7 Add hook regression tests that preserve supported skill/invocation hook normalization while legacy-gating agent-owned hook declarations.

## 2. Persistence profiles and durable child-run history

- [ ] 2.1 Define `closure_report.persistence_profile` metadata that reports transcript, child-run, job, task-list, team, and memory durability for the active runtime assembly using explicit durable / non-durable / host-provided states.
- [ ] 2.2 Add a first-party durable child-run store implementation and bind it through the initial production-oriented `runtime-full` persistence path.
- [ ] 2.3 Wire runtime assembly so `runtime-full` publishes and uses bundled durable transcript and child-run stores by default, while `runtime-core` / `runtime-default` explicitly publish their lighter durability contract.
- [ ] 2.4 Add focused tests that verify lightweight profiles remain explicitly non-durable while production-oriented profiles recover transcript and child-run history across reassembly.
- [ ] 2.5 Add metadata/regression tests that verify all declared persistence surfaces (jobs, task lists, team state, memory, transcript, child runs) are reported consistently in the active persistence profile with explicit durable / non-durable / host-provided states.

## 3. Isolation hardening

- [ ] 3.1 Replace the first-party `worktree` isolation stub with a deterministic filesystem-local lease implementation, structured lease metadata, and explicit cleanup-owner / cleanup-lifecycle semantics.
- [ ] 3.2 Replace successful `remote` stub leases with adapter-backed preparation/cleanup or structured not-configured/not-available failures, and publish adapter identity plus effective remote lease metadata when remote preparation succeeds.
- [ ] 3.3 Add cleanup, lifecycle, and delegation-boundary tests for hardened `worktree` and `remote` isolation semantics.

## 4. Assembly metadata and conformance gates

- [ ] 4.1 Publish the dedicated `closure_report` in runtime assembly metadata, separate from the stable core protocol catalog and package metadata.
- [ ] 4.2 Extend query/runtime inspection helpers so callers can inspect closure state, compatibility retirement, active persistence profile, and isolation readiness directly.
- [ ] 4.3 Extend the protocol-only conformance matrix with compatibility-retirement, persistence-profile, and isolation-readiness families plus stable per-assembly matrix metadata for each family result.
- [ ] 4.4 Add regression tests that require closure-green assemblies to avoid stub isolation, satisfy the declared persistence profile, and avoid hidden default legacy paths.

## 5. Documentation and migration cleanup

- [ ] 5.1 Update `docs/current-system-architecture.md` to explain why the microkernel rollout was structurally complete but not terminally closed, and to publish the final remaining gap list.
- [ ] 5.2 Update migration, integration, extension, and hook authoring guides to document legacy mode, closure-report inspection, persistence profiles, the retirement status of compatibility-only surfaces, and the split between supported skill/invocation hook normalization and legacy-gated agent-owned hook surfaces.
- [ ] 5.3 Add release/migration notes that map each retired or legacy-gated surface to its canonical replacement path.
