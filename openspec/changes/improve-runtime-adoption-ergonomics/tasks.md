## 1. Child delegation diagnostics

- [x] 1.1 Extend child result projection builders and `ChildSummaryProjection` so parent-visible child summaries expose a structured delegated `scope_summary` with at least `visible_tools`, `visible_skills`, `permission_mode`, and `isolation_mode` without changing the existing human summary text.
- [x] 1.2 Add focused tests for parent-visible agent results, child-run fallback projections, and `child_summary(...)` so delegated scope narrowing remains provable from public projection surfaces.

## 2. Assembly posture inspection

- [x] 2.1 Add a consolidated assembly posture report type and runtime/session helper that compose preset provenance, lightweight visible-invocation snapshots, lightweight invocation-diagnostics snapshots, and default-route preflight into one official inspection path.
- [x] 2.2 Update or add regression coverage for the new assembly posture helper, including a predictable missing-environment preflight failure path and assertions on the serialized posture snapshot shape.

## 3. Adoption guidance updates

- [x] 3.1 Update the canonical extension and hook docs with a copyable guarded-tool pattern plus explicit host-hook materialization and inventory guidance.
- [x] 3.2 Update the integration docs with explicit ownership guidance for `bind_host()` usage, helper-owned versus caller-owned report flows, and durable-resume re-assembly expectations.
- [x] 3.3 Update starter and demo guidance so the post-starter path from scaffold -> validation demos -> advanced host integration stays explicit, and refresh any affected demo findings ledger entries from `open` to `documented` or `follow-up landed` where this change closes the cited friction.

## 4. Validation and smoke coverage

- [x] 4.1 Add or update projection coverage in `tests/test_result_projections.py` so parent-visible and child-run-backed child summaries both preserve the new `scope_summary` contract.
- [x] 4.2 Add or update assembly posture coverage in `tests/test_runtime_kernel.py` or a focused equivalent test module so preset provenance, posture snapshots, and missing-environment preflight failure are asserted together.
- [x] 4.3 Update `tests/test_runtime_extension_examples.py` and re-run the affected demo/test paths, including `examples.agents.scoped_agent_delegation_demo`, `examples.runtime.assembly_diagnostics_demo`, `tests/test_result_projections.py`, and the new assembly posture coverage path.
