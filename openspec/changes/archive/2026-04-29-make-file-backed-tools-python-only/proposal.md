## Why

The current file-backed tool authoring surface looks broader than it really is: `.json` / `.yaml` / `.yml` tool files are discovered even though they cannot provide executable handlers, and `.py` modules may export mapping payloads that also degrade into non-executable tool definitions. This creates a misleading success path where discovery succeeds but runtime execution later fails with "no execution handler", so the authoring contract should be narrowed to the one path that is actually reliable.

## What Changes

- **BREAKING** Restrict file-backed tool discovery under `.weavert/tools/` to Python modules only (`*.py`).
- **BREAKING** Require discovered Python tool modules to export a concrete `ToolDefinition`; mapping-style exports are no longer accepted for file-backed tools.
- **BREAKING** Require discovered file-backed tools to provide `execute` during discovery so invalid tools fail fast with explicit diagnostics instead of surfacing as runtime execution errors.
- Emit direct rejection diagnostics when legacy `.json` / `.yaml` / `.yml` tool files are present so users can see why those files do not load.
- Update authoring and integration documentation to describe the Python-only tool contract.

## Capabilities

### New Capabilities
- None.

### Modified Capabilities
- `tool-system`: Change file-backed user tool discovery and validation requirements so `.weavert/tools/` accepts only executable Python tool modules with concrete `ToolDefinition` exports.

## Impact

- Affected code: tool discovery and validation in `src/weavert/registries/discovery.py`, related runtime guardrails in `src/weavert/tool_runtime.py`, and discovery tests.
- Affected APIs/contracts: file-backed tool authoring in `.weavert/tools/` becomes Python-only and requires `ToolDefinition` + `execute`.
- Affected users: any workspace relying on `.json` / `.yaml` / `.yml` tool files, or Python tool modules that export mapping payloads or omit `execute`, must be updated to the supported contract.
- Affected docs: `docs/weavert-definition-authoring-guide.md`, `docs/weavert-user-extension-guide.md`, and `docs/weavert-integration-guide.md`.
