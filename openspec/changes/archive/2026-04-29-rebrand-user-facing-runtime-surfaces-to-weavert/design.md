## Context

The current framework exposes multiple user-facing naming layers that no longer align with the intended WeaveRT product identity:

- package installation metadata uses `ai-agent-runtime`
- Python examples and public imports use `runtime`
- default user-visible workspace state uses `.runtime`
- first-party distributions and package names use `runtime-*`
- public capability, protocol, and extension-event namespaces use `runtime.*`

The agreed boundary for this change is "rename every surface a framework user or embedder directly touches, but do not force-renaming internal-only technical class names or private implementation terminology that does not leak into the public contract."

This is a cross-cutting change because the public naming contract is produced by packaging metadata, runtime bootstrap defaults, filesystem layout, package catalog metadata, protocol catalogs, host bridge events, and documentation at the same time. If those surfaces land inconsistently, embedders will see a mixed brand and migration guidance will become ambiguous.

## Goals / Non-Goals

**Goals:**

- Establish one canonical public naming contract based on `WeaveRT`, `weavert`, `.weavert`, `weavert-*`, and `weavert.*`.
- Rename the public Python import root and installation metadata so embedders bootstrap the framework through `weavert`.
- Rename the default user-visible workspace root so discovered definitions and persisted runtime data live under `.weavert`.
- Rename first-party distribution, package, capability, protocol, and extension-event identifiers that embedders inspect or configure directly.
- Update user-facing documentation and migration notes so all examples and paths converge on the new contract.

**Non-Goals:**

- Renaming internal-only technical class names such as `RuntimeConfig`, `RuntimeKernel`, or `TurnEngine` when those names do not appear as the public contract.
- Renaming historical OpenSpec archive content, test-only identifiers, or other non-user-facing repository artifacts.
- Preserving the old naming surfaces as co-equal documented public APIs after the rebrand lands.

## Decisions

### Decision: Treat the rebrand as a public-contract rename, not a cosmetic doc pass

This change will update code defaults, metadata emitters, and documented usage together. We will not stop at documentation-only renaming because the current user-visible names are emitted by runtime behavior as well as docs.

Rationale:

- package/import names, filesystem roots, distribution IDs, and protocol IDs are all observable framework contracts;
- leaving code defaults unchanged would preserve the old product identity in real integrations;
- a single change reduces the risk of documentation drifting away from runtime behavior.

Alternatives considered:

- docs-only rebrand: rejected because users would still install, import, configure, and inspect the old names;
- code-only rebrand with deferred docs: rejected because migration would be unreadable and error-prone.

### Decision: Canonical public Python entrypoint becomes `weavert`

The public Python package surface will move to `weavert`. The canonical user contract will be `pip install weavert` and `import weavert`, even if internal class names remain runtime-oriented.

Rationale:

- the package/import root is the most visible developer touchpoint;
- keeping `runtime` as the canonical import root would leave the old brand in every integration snippet;
- internal class names can remain stable without weakening the public rename.

Alternatives considered:

- keep shipping `runtime` as the primary import root and only rename docs: rejected because the public contract would still be the old name;
- ship `weavert` only as a thin documented alias while retaining `runtime` as a first-class public package: rejected because it preserves two public brands instead of one.

### Decision: Canonical workspace root becomes `.weavert`, with migration handling limited to legacy state ingestion

The canonical user-visible workspace root will move from `.runtime` to `.weavert`. The runtime may read or migrate legacy `.runtime` state where needed to avoid data loss, but `.runtime` will not remain a canonical documented root and new writes will target `.weavert`.

Rationale:

- users directly inspect and manage these directories;
- the current root leaks the old brand into every project-level customization path;
- read-or-migrate handling reduces upgrade pain without preserving the old root as the public contract.

Alternatives considered:

- keep `.runtime` permanently: rejected because it leaves the old brand in the most visible persistent surface;
- dual-write or dual-document `.runtime` and `.weavert`: rejected because it creates a long-lived split contract and complicates support.

### Decision: Rename all embedder-facing first-party identifiers in one coordinated pass

First-party distribution names, package IDs, package-owner metadata, capability keys, protocol IDs, and extension namespaces that embedders consume directly will be renamed together from `runtime-*` / `runtime.*` to `weavert-*` / `weavert.*`.

Rationale:

- embedders treat these identifiers as one connected public vocabulary;
- partial renaming would produce inconsistent metadata and migration guidance;
- coordinated renaming allows one migration note instead of several disconnected ones.

Alternatives considered:

- rename only install/import names first and defer metadata IDs: rejected because embedders would still configure and inspect the old names;
- keep `runtime.*` protocol names as permanent technical branding: rejected because these names are directly observable in user-facing diagnostics, host integrations, and extension events.

### Decision: Documentation follows the canonical contract immediately

All tracked user-facing framework guides and architecture docs that teach installation, import, project layout, package selection, or public metadata inspection will be updated in the same change.

Rationale:

- migration is part of the product contract here, not optional polish;
- stale examples would cause users to recreate legacy names immediately after the rebrand;
- the affected document set is already known and bounded.

Alternatives considered:

- defer docs until after code lands: rejected because the runtime change is intentionally breaking;
- update only quick-start material: rejected because advanced embedder docs also surface public package IDs and namespaces.

## Risks / Trade-offs

- [Broad surface area] → Mitigation: implement in slices that follow the public contract order: package/import root, workspace root, then metadata/package/namespace surfaces, with docs updated alongside each slice.
- [Legacy persisted state becomes stranded] → Mitigation: treat `.runtime` as legacy input for migration or one-time discovery where necessary, but write canonical state to `.weavert`.
- [Mixed naming appears in metadata or docs] → Mitigation: update metadata-producing code paths and user-facing guides in the same change and add verification for canonical names.
- [Over-renaming internal code increases churn] → Mitigation: preserve internal-only technical class names and target only surfaces users or embedders can directly touch.
- [Breaking changes surprise existing embedders] → Mitigation: include explicit migration notes for installs, imports, workspace paths, first-party package IDs, and public namespaces.

## Migration Plan

1. Introduce the canonical WeaveRT naming contract in specs and implementation entrypoints first: installation metadata, import root, and default discovery roots.
2. Rename the default user-visible workspace root to `.weavert` and update persisted-state path producers, with controlled legacy `.runtime` ingestion where required for upgrade safety.
3. Rename first-party distribution/package identifiers and public namespace emitters so runtime metadata, package selection, and host extension events all converge on `weavert-*` and `weavert.*`.
4. Update all tracked user-facing framework docs and migration notes to use the new canonical contract and document the required upgrade steps.
5. Verify that no canonical user-facing examples or metadata outputs still advertise the old names.

Rollback strategy:

- revert the change before release if verification still shows mixed public names;
- do not ship a half-renamed contract where docs and emitted runtime metadata disagree.

## Open Questions

- Do we need a short-lived config normalizer for legacy `runtime-*` first-party package names during upgrade, or is migration documentation alone sufficient for the first release of the rebrand?
