## 1. Public package and import surface

- [ ] 1.1 Encode the canonical WeaveRT name mapping for install name, import root, workspace root, first-party package IDs, distribution IDs, and public namespace prefixes.
- [ ] 1.2 Rename the public Python package surface from `ai-agent-runtime` / `runtime` to `weavert`, including package metadata and tracked public import examples.
- [ ] 1.3 Update runtime bootstrap and public entrypoint wiring so embedders use `weavert` as the canonical import path without exposing the old names as the primary contract.

## 2. User-visible workspace root and persisted state

- [ ] 2.1 Rename default discovery roots from `~/.runtime` and `<project>/.runtime` to `~/.weavert` and `<project>/.weavert`.
- [ ] 2.2 Rename canonical user-visible persisted state layouts from `.runtime/**` to `.weavert/**` across discovered definitions, memory, transcript, task, team, mailbox, and isolation paths.
- [ ] 2.3 Add controlled legacy `.runtime` ingestion or migration behavior where needed so persisted user state does not become stranded during upgrade.

## 3. First-party package identifiers and public namespaces

- [ ] 3.1 Rename first-party distribution and package identifiers from `runtime-*` to `weavert-*` in package profiles, package catalogs, package manifests, and package resolution surfaces.
- [ ] 3.2 Rename public capability keys, protocol identifiers, host-facet identifiers, and extension-event namespaces from `runtime.*` to `weavert.*`.
- [ ] 3.3 Update assembly metadata, inspection helpers, and built-in ownership metadata so tracked public outputs advertise only canonical WeaveRT names.

## 4. User-facing documentation and migration guidance

- [ ] 4.1 Update tracked user-facing framework guides and architecture docs to use `WeaveRT`, `weavert`, `.weavert`, `weavert-*`, and `weavert.*` consistently.
- [ ] 4.2 Add explicit migration guidance for install names, import paths, workspace roots, first-party package IDs, and public namespaces.

## 5. Verification

- [ ] 5.1 Add or update verification coverage for the public import root, default `.weavert` discovery and persistence paths, renamed first-party package IDs, and renamed public namespaces.
- [ ] 5.2 Run focused verification that tracked canonical docs and emitted public metadata no longer advertise `ai-agent-runtime`, `runtime`, `.runtime`, `runtime-*`, or `runtime.*` as primary user-facing names.
