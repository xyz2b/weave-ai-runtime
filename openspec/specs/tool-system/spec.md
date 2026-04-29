# tool-system Specification

## Purpose
TBD - created by archiving change python-agent-runtime-foundation. Update Purpose after archive.
## Requirements
### Requirement: 参考实现兼容的 tool 定义
runtime SHALL 支持保持参考实现兼容字段与语义的 executable `ToolDefinition` objects，包括 naming、aliases、schema、validation、permission checks、execution 与 execution traits；对于 `.weavert/tools/` 下的 file-backed 用户工具，runtime SHALL 仅接受 Python modules，并 SHALL 仅从 `TOOL_DEFINITION`、`TOOL` 或 `build_tool_definition()` 解析模块导出，且解析结果 SHALL 是带有 executable handler 的 concrete `ToolDefinition`。

#### Scenario: 加载可执行的 Python file-backed tool
- **WHEN** 用户在 `.weavert/tools/` 下定义了一个 Python module
- **AND** 该 module 通过 `TOOL_DEFINITION`、`TOOL` 或 `build_tool_definition()` 导出包含名称、input schema、validation logic、permission logic、execution traits 与 `execute` 的 concrete `ToolDefinition`
- **THEN** runtime SHALL 注册并执行该 tool

#### Scenario: 拒绝 legacy JSON/YAML file-backed tool
- **WHEN** `.weavert/tools/` 下存在 `.json`、`.yaml` 或 `.yml` tool file
- **THEN** runtime SHALL NOT 将该文件注册为可用 tool
- **AND** SHALL 产出明确说明仅支持 Python file-backed tool 的 discovery diagnostic

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

### Requirement: tool pool resolution
runtime SHALL 使用与参考实现兼容的 wildcard、allow-list 与 disallow-list 语义，为主线程与 subagents 解析 tool pools。

#### Scenario: 按 agent 过滤 tools
- **WHEN** 某个 agent definition 声明了 `tools`、`disallowedTools` 或 wildcard tool access
- **THEN** runtime SHALL 在当前可用 runtime tools 之上应用这些 agent 规则，并解析出最终 tool pool

### Requirement: tool orchestration 遵守 execution traits
runtime SHALL 根据 tool 声明的 concurrency 与 read-only 语义来编排 tool calls。

#### Scenario: 单个 turn 中混合只读与变更型 tools
- **WHEN** 某个 turn 包含多个 tool calls，其中一部分是 concurrency-safe 的只读操作，另一部分是有副作用的变更型操作
- **THEN** runtime SHALL 允许只读操作并发执行，并 SHALL 将变更型操作串行化
