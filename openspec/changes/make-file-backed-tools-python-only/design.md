## Context

The runtime currently advertises a broader file-backed tool authoring surface than it can reliably execute. `DefinitionDiscovery` scans `.weavert/tools/` for `.json`, `.yaml`, `.yml`, and `.py` files, but only Python modules can realistically supply executable behavior. The mapping loader used for JSON/YAML payloads and Python `dict` exports constructs `ToolDefinition` objects from schema-style fields only, so these definitions can be discovered successfully and still fail later at tool execution time with a missing-handler error.

This change is cross-cutting because it affects discovery, validation timing, diagnostics, tests, and documentation. It does not change built-in tool registration or programmatic `ToolDefinition` injection, but it does intentionally tighten the file-backed authoring contract exposed to users.

## Goals / Non-Goals

**Goals:**
- Make `.weavert/tools/` authoring truthful by supporting only the executable path the runtime can honor.
- Move invalid file-backed tool failures from runtime execution time to discovery time with explicit diagnostics.
- Keep the object-level `ToolDefinition` model intact for built-ins and programmatic registration while narrowing only the filesystem authoring surface.

**Non-Goals:**
- Changing built-in tool registration, package-contributed tools, or any non-file-backed tool registration path.
- Redesigning `ToolDefinition` itself or changing tool pool semantics for agents and subagents.
- Introducing a new compatibility flag or alternate legacy file-backed tool executor.
- Expanding this change to agent, skill, or hook authoring surfaces.

## Decisions

### 1. File-backed tool discovery becomes Python-only

`.weavert/tools/` discovery will treat `*.py` as the only supported authoring format for user tools. Legacy `.json`, `.yaml`, and `.yml` files will no longer be loaded as tools.

Rationale:
- The current multi-format surface is misleading because non-Python files cannot express executable handlers.
- Restricting discovery to a single executable format makes the contract obvious and removes a major source of false-positive discovery success.

Alternatives considered:
- Keep legacy formats and document them as metadata-only. Rejected because the user-visible failure mode still looks like a valid tool until execution time.
- Silently ignore legacy formats. Rejected because users would lose visibility into why a previously present file no longer has effect.

### 2. Python tool modules must export a concrete `ToolDefinition`

Discovered Python tool modules will continue to support `TOOL_DEFINITION`, `TOOL`, and `build_tool_definition()`, but all accepted entrypoints must resolve to a concrete `ToolDefinition` instance. Mapping-style exports will be rejected for file-backed tools.

Rationale:
- Allowing `dict` exports reintroduces the same non-executable hydration path that caused the ambiguity in JSON/YAML discovery.
- Requiring an actual `ToolDefinition` keeps the file-backed contract aligned with the runtime's executable model.

Alternatives considered:
- Continue accepting `dict` payloads from Python modules. Rejected because the loader cannot reliably reconstruct callable fields such as `execute`, `validate_input`, and `check_permissions`.
- Add a richer Python mapping schema for callable references. Rejected because it creates a second, more complex authoring language when a direct Python object already exists.

### 3. File-backed tools must fail fast if `execute` is missing

Discovery-time validation will reject any file-backed Python tool whose `ToolDefinition.execute` is `None`. The runtime execution guard for missing handlers remains as a defensive boundary for non-file-backed definitions, but it is no longer the primary validation path for `.weavert/tools/`.

Rationale:
- User-authored filesystem tools are intended to be executable capabilities, not metadata stubs.
- Discovery-time validation produces a much clearer authoring loop than surfacing the error only after model planning reaches the tool.

Alternatives considered:
- Preserve the current runtime-only guard. Rejected because it delays failure and makes broken tools appear successfully installed.
- Auto-wrap missing handlers with a stub error executor. Rejected because it still advertises unusable tools in the capability graph.

### 4. Legacy file-backed formats receive direct rejection diagnostics

When unsupported legacy tool files are present, discovery will emit direct rejection diagnostics that point at the file and explain the Python-only contract. Similar diagnostics will be emitted for invalid Python exports and missing `execute`. At minimum, these diagnostics should identify the file path and the rejection reason.

Rationale:
- The change is intentionally breaking, so users need direct local feedback instead of silent failure.
- Diagnostics preserve debuggability without preserving the misleading authoring path itself.

Alternatives considered:
- Emit no diagnostic and rely entirely on silent skipping. Rejected because the failure would look like silent disappearance.
- Add a temporary compatibility flag. Rejected because it prolongs the dual-surface ambiguity that this change is trying to eliminate.

## Risks / Trade-offs

- [Breaking existing workspaces with YAML/JSON tools] -> Emit explicit rejection diagnostics and update all examples to the Python-only path.
- [Breaking Python modules that export mappings] -> Reject them with targeted validation errors and document the requirement to export a concrete `ToolDefinition`.
- [Over-tightening beyond file-backed tools] -> Keep the runtime no-handler guard and preserve programmatic/built-in `ToolDefinition` registration paths unchanged.
- [Confusion about whether tool metadata-only use cases are still supported] -> State clearly that metadata-only filesystem tools are no longer a supported authoring surface; such use cases must move to programmatic registration or a future dedicated extension mechanism.

## Migration Plan

1. Update authoring and integration docs so the canonical path is unambiguously `.weavert/tools/*.py`.
2. Change discovery to scan for Python modules as supported tools and emit rejection diagnostics for legacy file extensions that remain in `.weavert/tools/`.
3. Tighten Python export validation so file-backed tools must resolve to `ToolDefinition` and must include `execute`.
4. Update discovery tests to treat YAML/JSON files and mapping-style Python exports as rejection cases instead of successful discovery cases.
5. Keep the runtime missing-handler guard as a defensive fallback for non-file-backed definitions.

Rollback would consist of restoring the removed discovery branches for legacy formats and mapping-style exports, but the intended rollout path is a direct contract change rather than a staged compatibility mode.

## Open Questions

- None for this change; the proposal intentionally chooses a direct contract simplification over a staged compatibility flag.
