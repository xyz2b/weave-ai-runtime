## 1. Context Authority Migration

- [ ] 1.1 Identify and centralize raw `runtime_context` normalization at API-boundary and compatibility-adapter entry points.
- [ ] 1.2 Route authoritative private-state writes through `RuntimePrivateContext`, ingress private updates, and prompt/private carrier helpers only.
- [ ] 1.3 Remove runtime-owned primary-path logic that still depends on raw `runtime_context` as an authoritative mutable state bag.

## 2. TaskManager Compatibility Reduction

- [ ] 2.1 Remove runtime-owned primary-path dependence on `TaskManager` materialization and direct authority.
- [ ] 2.2 Keep `TaskManager` available only as an explicit legacy facade over `JobService` and `TaskListService` where compatibility still requires it.

## 3. Contract and Metadata Hardening

- [ ] 3.1 Publish metadata that marks raw `runtime_context` and `TaskManager` as compatibility-only surfaces.
- [ ] 3.2 Update owner-layer helpers and docs to use structured context carriers and shared job/task services as the authoritative contract.
- [ ] 3.3 Publish an explicit whitelist of the remaining compatibility-only `runtime_context` entry points and `TaskManager` materialization adapters, with exit criteria for removing each.

## 4. Verification

- [ ] 4.1 Add conformance and regression coverage that detects authoritative raw `runtime_context` writes in primary paths.
- [ ] 4.2 Add conformance and regression coverage that detects new primary-path dependence on `TaskManager`.
- [ ] 4.3 Publish structured conformance findings for the context-authority and task-authority rules so the terminal protocol-only gate can aggregate them without re-auditing call sites.
