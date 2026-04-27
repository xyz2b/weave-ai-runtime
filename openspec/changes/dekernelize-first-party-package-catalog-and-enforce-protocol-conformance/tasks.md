## 1. Official Catalog Ownership

- [ ] 1.1 Introduce the manifest-backed official first-party package catalog provider and migrate existing official package catalog data into it.
- [ ] 1.2 Update supported distribution composition logic to consume the official package catalog provider rather than kernel-owned assembly switch tables.

## 2. Assembly and Provenance Publication

- [ ] 2.1 Publish official package-catalog provenance and resolved active package-graph provenance in runtime assembly metadata.
- [ ] 2.2 Publish a protocol-only conformance summary with per-rule findings for the privileged-service-slot, context-authority, team-bridge, provider-provenance, and kernel-assembly rule families, using the shared finding fields `rule_id`, `family`, `status`, `distribution`, `evidence`, `canonical_path`, and optional `compat_surface` or `replacement_path`.
- [ ] 2.3 Expose the same summary through the assembled runtime query surface used by CI and embedders.

## 3. Conformance Enforcement

- [ ] 3.1 Define the initial forbidden compatibility-surface and forbidden assembly-branch rule set, the shared finding schema, and the mapping from each rule to the structured finding source that owns it.
- [ ] 3.2 Add conformance and regression coverage across `runtime-core`, `runtime-default`, and `runtime-full`, including optional-package present or absent cases, that evaluates the aggregated summary.
- [ ] 3.3 Turn the aggregated summary into a failing protocol-only gate once the earlier four rule families are green, where green means every rule family reports `pass` across `runtime-core`, `runtime-default`, `runtime-full`, and the required optional-package present or absent cases.

## 4. Retirement and Documentation

- [ ] 4.1 Remove or retire the superseded kernel-owned catalog tables and switch helpers once the catalog-backed path is proven.
- [ ] 4.2 Update architecture, package, and conformance docs to describe catalog ownership, the aggregated summary, and the terminal protocol-only gate.
