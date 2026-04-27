## Context

Today package selection is simple: choose a set of package names, look up one manifest per name, and run `order_package_manifests()` over the resulting dependency graph. That works because the runtime currently owns a fixed official package set and each package name maps to exactly one manifest.

That model breaks as soon as external registration or versioned package evolution becomes real. Registration tells the runtime which package candidates exist; a resolver is what decides which candidate graph is actually valid for a given distribution or embedder request. Those two responsibilities need to remain separate.

## Goals / Non-Goals

**Goals:**

- Introduce a local package catalog that can hold multiple candidates safely.
- Define deterministic dependency and compatibility resolution before assembly.
- Preserve a migration path from current flat manifest dependencies to richer candidate selection.
- Keep resolution diagnostics explicit and machine-readable.

**Non-Goals:**

- Installing packages, fetching remote packages, or managing Python environment dependencies.
- Designing a public marketplace or publication workflow.
- Replacing package contribution assembly itself.
- Solving every future package-feature toggle or lockfile concern in one step.

## Decisions

### 1. Registration and resolution stay separate

External registration determines which candidates are known to the runtime. Resolution determines which candidate graph will be assembled for a particular runtime instance. This change assumes registration has already occurred and operates over the registered candidate set.

Why this decision:

- it keeps responsibilities clean
- it lets registration remain simple and local
- it allows better diagnostics for each phase

Alternatives considered:

- combine registration and resolution in one implicit step: rejected because it hides too many failure modes behind one operation

### 2. The catalog wraps manifests instead of replacing them

The resolver will introduce a package-candidate descriptor around `RuntimePackageManifest` rather than forcing manifest contribution assembly to carry all catalog metadata directly. Candidate descriptors can hold source, version, compatibility metadata, and dependency constraints while the manifest remains the assembly contract.

Why this decision:

- it minimizes churn to existing package contribution code
- it keeps assembly concerns separate from candidate-selection concerns
- it supports incremental migration from today’s manifest shape

Alternatives considered:

- expand `RuntimePackageManifest` into a full catalog record immediately: rejected because it would entangle assembly and resolution responsibilities too early

### 3. Initial constraint support is bounded

The initial resolver should support exact version references and a small compatible-range vocabulary, while preserving a compatibility path for current first-party manifests that only declare flat package-name dependencies.

Why this decision:

- it covers the most likely near-term needs without overdesigning a solver
- it keeps first-party migration practical
- it avoids locking the runtime into a hidden “latest wins” policy

Alternatives considered:

- exact-match only forever: rejected because it would make a catalog barely more expressive than today’s manifest list
- full package-manager-grade solver immediately: rejected because it is too much scope for the runtime’s actual needs

### 4. Resolution output feeds existing dependency ordering

Once the resolver selects one candidate per package name for the requested runtime, the existing dependency-ordering and package-contribution assembly flow remains the downstream path.

Why this decision:

- it isolates the new work to pre-assembly selection
- it reduces implementation risk
- it keeps the runtime’s assembly model stable while selection evolves

Alternatives considered:

- rewrite package assembly and ordering at the same time: rejected because it conflates two separate concerns

## Risks / Trade-offs

- [A bounded initial constraint language may need revision later] -> Mitigation: keep the candidate descriptor and diagnostics structured so the constraint vocabulary can evolve without hiding behavior.
- [Two parallel dependency models may exist during migration] -> Mitigation: document the flat `dependencies` tuple as a compatibility path and keep resolution diagnostics explicit about which model was used.
- [Resolver complexity could grow toward package-manager scope] -> Mitigation: keep the resolver local, install-agnostic, and focused only on selecting runtime package candidates.
- [Catalog metadata could drift from actual assembled manifests] -> Mitigation: derive resolved-graph metadata directly from the selected candidate set that is handed to assembly.

## Migration Plan

1. Introduce a local package-candidate descriptor and catalog container around existing manifests.
2. Seed the catalog with the current official first-party packages as one fixed candidate per package name.
3. Resolve runtime distribution requests and explicit package requests into a concrete manifest graph before existing dependency ordering runs.
4. Surface resolution diagnostics and resolved-graph metadata in runtime assembly outputs and docs.

Rollback is manageable because the runtime can temporarily fall back to today’s one-manifest-per-name selection path while keeping the catalog data structures behind a feature gate or compatibility layer.

## Open Questions

- Should optional feature groups or profile flags be modeled as resolver inputs in this change, or should they remain a later extension after base candidate selection is stable?
- When lockfile-like reproducibility becomes necessary, should it be layered on top of resolved package graphs or treated as a separate runtime-distribution artifact?
