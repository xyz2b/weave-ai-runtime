## 1. Discovery contract tightening

- [ ] 1.1 Restrict `.weavert/tools/` discovery to Python modules only.
- [ ] 1.2 Emit explicit migration diagnostics for legacy `.json`, `.yaml`, and `.yml` tool files found under `.weavert/tools/`.
- [ ] 1.3 Remove mapping-style file-backed tool hydration from Python module loading.
- [ ] 1.4 Require discovered Python tool modules to resolve to a concrete `ToolDefinition` via `TOOL_DEFINITION`, `TOOL`, or `build_tool_definition()`.
- [ ] 1.5 Validate discovered file-backed tools for `execute` before registration.
- [ ] 1.6 Keep the runtime missing-handler guard as a defensive fallback for non-file-backed definitions.

## 2. Tests and validation coverage

- [ ] 2.1 Update discovery tests so executable Python tool modules remain accepted.
- [ ] 2.2 Add rejection coverage for legacy YAML/JSON file-backed tools, including diagnostics that identify the file path, rejection reason, and migration target.
- [ ] 2.3 Add negative coverage for Python tool modules that export mappings instead of `ToolDefinition`.
- [ ] 2.4 Add negative coverage for discovered `ToolDefinition` instances that omit `execute`.
- [ ] 2.5 Verify rejected file-backed tools do not enter the active tool registry or capability graph.
- [ ] 2.6 Verify existing built-in and programmatic tool registration paths still behave correctly after the file-backed authoring surface is narrowed.

## 3. Docs and migration guidance

- [ ] 3.1 Update `docs/weavert-definition-authoring-guide.md` so discovery rules and examples describe Python-only file-backed tool authoring.
- [ ] 3.2 Update `docs/weavert-user-extension-guide.md` so the recommended user tool contract is concrete `ToolDefinition` + `execute` in `.py` modules only.
- [ ] 3.3 Update `docs/weavert-integration-guide.md` so project layout and bootstrap examples no longer advertise YAML/JSON file-backed tools.
- [ ] 3.4 Update `docs/weavert-migration-notes.md` with the breaking change, affected authoring patterns, and the new Python-only file-backed tool contract.
- [ ] 3.5 Add migration examples showing `legacy yaml/json tool -> Python ToolDefinition module` and `mapping-style Python export -> concrete ToolDefinition export`.
