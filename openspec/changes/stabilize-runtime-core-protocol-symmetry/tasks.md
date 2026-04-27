## 1. Protocol Catalog Model

- [ ] 1.1 Define the stable core protocol catalog model, including schema version, canonical protocol name, owner, binding boundary, discovery surface, and compatibility status.
- [ ] 1.2 Populate the catalog for transcript persistence, job control, task-list control, permission, elicitation, context contributors, invocation providers, and host binding.
- [ ] 1.3 Decide where protocol catalog data lives in runtime assembly metadata and how it is surfaced for docs and tests.

## 2. Assembly And Metadata Integration

- [ ] 2.1 Update runtime assembly to publish stable core protocol metadata separately from first-party package inventory and package-lookup metadata, with the protocol catalog as the source of truth for stable core protocols.
- [ ] 2.2 Mark compatibility-only helper surfaces explicitly in the protocol catalog or adjacent metadata without promoting them to canonical protocol entries.
- [ ] 2.3 Ensure supported distributions preserve the same core protocol identities while still reporting their package-specific additions separately, and keep package-lookup metadata as the source of truth for package-specific canonical keys and wrapper status.

## 3. Documentation

- [ ] 3.1 Update architecture and integration guides to describe the stable core protocol catalog and the canonical binding story for each protocol class.
- [ ] 3.2 Update migration notes to distinguish stable core protocols from optional package capabilities and retained compatibility wrappers.
- [ ] 3.3 Align user-extension guidance so embedders know which seams are config-owned, service-owned, registry-owned, or host-bound.

## 4. Conformance

- [ ] 4.1 Add conformance coverage that verifies supported runtime distributions publish the same stable core protocol identities and schema version.
- [ ] 4.2 Add tests that verify protocol catalog metadata remains separate from package inventory and compatibility projection metadata.
- [ ] 4.3 Add regression coverage that catches accidental relabeling of package capabilities or wrappers as stable core protocols.
