## 1. Discovery contract tightening

- [x] 1.1 Restrict `.weavert/tools/` discovery to Python modules only.
- [x] 1.2 Emit explicit rejection diagnostics for legacy `.json`, `.yaml`, and `.yml` tool files found under `.weavert/tools/`.
- [x] 1.3 Remove mapping-style file-backed tool hydration from Python module loading.
- [x] 1.4 Require discovered Python tool modules to resolve to a concrete `ToolDefinition` via `TOOL_DEFINITION`, `TOOL`, or `build_tool_definition()`.
- [x] 1.5 Validate discovered file-backed tools for `execute` before registration.
- [x] 1.6 Keep the runtime missing-handler guard as a defensive fallback for non-file-backed definitions.

## 2. Tests and validation coverage

- [x] 2.1 Update discovery tests so executable Python tool modules remain accepted.
- [x] 2.2 Add rejection coverage for legacy YAML/JSON file-backed tools, including diagnostics that identify the file path and rejection reason.
- [x] 2.3 Add negative coverage for Python tool modules that export mappings instead of `ToolDefinition`.
- [x] 2.4 Add negative coverage for discovered `ToolDefinition` instances that omit `execute`.
- [x] 2.5 Verify rejected file-backed tools do not enter the active tool registry or capability graph.
- [x] 2.6 Verify existing built-in and programmatic tool registration paths still behave correctly after the file-backed authoring surface is narrowed.

## 3. Docs

- [x] 3.1 Update `docs/weavert-definition-authoring-guide.md` so discovery rules and examples describe Python-only file-backed tool authoring.
- [x] 3.2 Update `docs/weavert-user-extension-guide.md` so the recommended user tool contract is concrete `ToolDefinition` + `execute` in `.py` modules only.
- [x] 3.3 Update `docs/weavert-integration-guide.md` so project layout and bootstrap examples no longer advertise YAML/JSON file-backed tools.
