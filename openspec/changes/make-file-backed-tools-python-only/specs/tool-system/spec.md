## MODIFIED Requirements

### Requirement: 参考实现兼容的 tool 定义
runtime SHALL 支持保持参考实现兼容字段与语义的 executable `ToolDefinition` objects，包括 naming、aliases、schema、validation、permission checks、execution 与 execution traits；对于 `.weavert/tools/` 下的 file-backed 用户工具，runtime SHALL 仅接受 Python modules，并 SHALL 仅从 `TOOL_DEFINITION`、`TOOL` 或 `build_tool_definition()` 解析模块导出，且解析结果 SHALL 是带有 executable handler 的 concrete `ToolDefinition`。

#### Scenario: 加载可执行的 Python file-backed tool
- **WHEN** 用户在 `.weavert/tools/` 下定义了一个 Python module
- **AND** 该 module 通过 `TOOL_DEFINITION`、`TOOL` 或 `build_tool_definition()` 导出包含名称、input schema、validation logic、permission logic、execution traits 与 `execute` 的 concrete `ToolDefinition`
- **THEN** runtime SHALL 注册并执行该 tool

#### Scenario: 拒绝 legacy JSON/YAML file-backed tool
- **WHEN** `.weavert/tools/` 下存在 `.json`、`.yaml` 或 `.yml` tool file
- **THEN** runtime SHALL NOT 将该文件注册为可用 tool
- **AND** SHALL 产出明确说明 Python-only file-backed tool contract 的 discovery diagnostic

#### Scenario: 拒绝 mapping-style Python tool export
- **WHEN** `.weavert/tools/` 下的 Python tool module 导出 mapping-style payload 而不是 concrete `ToolDefinition`
- **THEN** runtime SHALL NOT 将该 module 注册为可用 tool
- **AND** SHALL 产出要求导出 concrete `ToolDefinition` 的 discovery diagnostic

#### Scenario: 在 discovery 阶段拒绝缺少 execute 的 file-backed tool
- **WHEN** `.weavert/tools/` 下的 Python tool module 导出的 `ToolDefinition` 缺少 `execute`
- **THEN** runtime SHALL 在 discovery 阶段拒绝该 tool
- **AND** SHALL 产出指明 file-backed tools MUST provide `execute` 的 diagnostic

#### Scenario: 非 file-backed tool registration path 保持不变
- **WHEN** runtime 通过 built-in registration、programmatic `ToolDefinition` injection、或其他非 `.weavert/tools/` 的路径获得 executable `ToolDefinition`
- **THEN** runtime SHALL 继续注册并执行这些 tools
- **AND** SHALL NOT 将 Python-only filesystem authoring contract 施加到这些非 file-backed registration paths
