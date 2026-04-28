## Why

The runtime's protocol-first microkernel shape is now real: package manifests, contribution assembly, capability lookup, lifecycle phases, host facets, stable core protocol metadata, and protocol-only conformance are all in place. But the rollout still stops short of terminal closure because a small set of compatibility-only surfaces remains publicly visible, `worktree` / `remote` isolation are still stub-grade, and durable transcript / child-run behavior is not yet a bundled default story.

That leaves the framework in an awkward middle state: architecturally correct, but not yet finished enough to call the microkernel rollout complete. After two rounds and many changes, the next step should not be another partial seam cleanup; it should be one explicit closure change that retires the remaining boundary leaks, hardens the weak mechanism packages, and publishes a final readiness story that embedders can trust.

## What Changes

- Add an explicit runtime compatibility-retirement contract that defines how remaining legacy surfaces such as `TaskManager`, shared authoritative `runtime_context` writes, package-specific compatibility projections, and legacy agent-owned hook authoring paths are retired, gated, or isolated behind an explicit legacy mode.
- Add a runtime persistence-profile contract that defines bundled transcript and child-run durability expectations by distribution/profile, including a first-party durable default path for production-oriented runtimes instead of leaving child-run durability entirely to ad hoc host injection.
- Harden isolation so `worktree` and `remote` are no longer "prepared=true, stub=true" placeholders; the runtime must provide concrete preparation, lease metadata, and cleanup semantics for those modes.
- Publish closure-oriented assembly metadata and conformance output that make it obvious whether a runtime is still relying on retained compatibility surfaces, stub isolation, or non-durable execution history defaults.
- **BREAKING** Narrow or remove remaining compatibility-first public surfaces from the default primary path, including legacy agent-owned hook authoring paths that still look like ordinary v1 extensibility even though the architecture now treats them as compatibility-only.

## Capabilities

### New Capabilities
- `runtime-compatibility-retirement`: terminal retirement policy, legacy-mode behavior, and closure metadata for remaining compatibility-only runtime surfaces.
- `runtime-persistence-profiles`: bundled persistence profiles for transcript and child-run durability, plus the package/distribution rules that activate them.

### Modified Capabilities
- `runtime-isolation-control-plane`: isolation modes gain non-stub runtime semantics and stronger lease/cleanup guarantees.
- `child-run-observability`: child-run records gain a bundled durable-default story for production-oriented runtimes without weakening the existing continuation and host-observability contract.
- `runtime-hook-configuration-platform`: legacy agent-owned hook surfaces are demoted from ordinary public authoring to explicit legacy compatibility behavior, while supported skill/invocation normalization remains public.
- `query-runtime-assembly`: assembly metadata reports closure state, retained legacy surfaces, persistence profile, and isolation readiness separately from the stable core protocol catalog.
- `query-runtime-conformance`: conformance gates extend to compatibility retirement, persistence-profile expectations, and non-stub isolation behavior.

## Impact

- Affected code: `src/runtime/runtime_kernel/`, `src/runtime/runtime_services/`, `src/runtime/runtime_package_protocols.py`, `src/runtime/runtime_package_manifests.py`, `src/runtime/runtime_core_protocol_catalog.py`, `src/runtime/isolation.py`, `src/runtime/isolation_package.py`, `src/runtime/agent_runtime.py`, `src/runtime/agent_execution.py`, `src/runtime/agent_execution_service.py`, `src/runtime/stores_file/`, `src/runtime/registries/agent_registry.py`, and related host/runtime query surfaces.
- Affected docs: `docs/current-system-architecture.md`, migration/integration/extension guides, and any architecture diagrams that currently blur "implemented main path" with "still retained compatibility path".
- Runtime/API impact: embedders may need to opt into an explicit legacy mode for retained compatibility access, migrate off deprecated hook/frontmatter patterns, and rely on published persistence profiles instead of assuming all distributions behave the same.
- Testing impact: distribution-matrix conformance coverage expands to include closure status, persistence defaults, and concrete isolation behavior.
