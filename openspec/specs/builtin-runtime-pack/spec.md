# builtin-runtime-pack Specification

## Purpose
TBD - created by archiving change python-agent-runtime-foundation. Update Purpose after archive.
## Requirements
### Requirement: 内置 tool pack
runtime SHALL 默认随附一个内置 tool pack，其中包括 `read`、`edit`、`write`、`glob`、`grep`、`bash`、`web_fetch`、`web_search`、`agent`、`skill`、`task_create`、`task_get`、`task_update`、`task_list`、`task_stop`、`ask_user` 与 `sleep`。

#### Scenario: 无自定义 tools 时启动 runtime
- **WHEN** runtime 在没有用户自定义 tools 的情况下启动
- **THEN** 内置 tool pack SHALL 仍然被注册，并根据 tool-pool resolution 规则可供 runtime 使用

### Requirement: 内置 agent pack
runtime SHALL 随附内置 agents：`main-router`、`general-purpose`、`explore`、`plan` 和 `verification`。

#### Scenario: 无自定义 agents 时启动 runtime
- **WHEN** runtime 在没有用户自定义 agents 的情况下启动
- **THEN** 内置 agent pack SHALL 仍然被注册，并可用于主线程和委派执行

### Requirement: 内置 skill pack
runtime SHALL 随附内置 skills：`verify`、`debug`、`stuck`、`batch`、`simplify` 和 `remember`。

#### Scenario: 无自定义 skills 时启动 runtime
- **WHEN** runtime 在没有用户自定义 skills 的情况下启动
- **THEN** 内置 skill pack SHALL 仍然被注册，并根据 skill discovery 与 activation 规则在 session 中可用

### Requirement: 内置 pack 仍然可配置
runtime SHALL 允许 host 或应用扩展或选择性禁用内置 runtime packs，而不需要改变 built-in definition format。

#### Scenario: host 禁用某个 built-in
- **WHEN** 某个 host 配置禁用了某个内置 runtime 定义
- **THEN** runtime SHALL 应用该启用状态覆盖，同时保持其余 built-ins 的定义契约不变

### Requirement: Built-in runtime pack includes a first-party OpenAI provider baseline
The runtime SHALL bundle a first-party OpenAI provider integration as part of the built-in runtime pack, together with default named-route-ready definitions or equivalent provider wiring that hosts may use directly or override.

#### Scenario: Runtime boots without custom provider integrations
- **WHEN** the runtime starts with only bundled runtime definitions
- **THEN** it SHALL still expose a usable first-party OpenAI provider integration baseline
- **AND** SHALL allow hosts to supply credentials, route overrides, or model overrides without requiring a separate third-party OpenAI plugin to be installed first

#### Scenario: Built-in OpenAI provider baseline participates in context-window-aware execution
- **WHEN** the bundled first-party OpenAI provider integration is used through a named route
- **THEN** it SHALL be able to provide context window profiles and minimal recovery classification hints under the same contract as third-party integrations
- **AND** SHALL NOT require special-case runtime logic outside the shared integration and route-resolution path

#### Scenario: Built-in OpenAI provider baseline exposes canonical route names and env overrides
- **WHEN** the runtime loads its bundled first-party OpenAI provider baseline
- **THEN** it SHALL expose a default provider binding named `openai-prod`
- **AND** SHALL expose a default named route `openai_default`
- **AND** SHALL recognize `OPENAI_API_KEY` for credentials together with optional `OPENAI_BASE_URL` and `OPENAI_MODEL` overrides or equivalent host-supplied replacements

#### Scenario: Missing bundled OpenAI credentials does not remove the route definition
- **WHEN** the bundled OpenAI route definitions are available but `OPENAI_API_KEY` has not been supplied and the host has not overridden credentials
- **THEN** the runtime SHALL still allow the OpenAI route baseline to be discovered and overridden
- **AND** SHALL fail invocation with a structured configuration or credential error rather than silently removing the built-in route from discovery
