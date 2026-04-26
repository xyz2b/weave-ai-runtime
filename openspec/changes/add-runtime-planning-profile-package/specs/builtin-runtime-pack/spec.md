## MODIFIED Requirements

### Requirement: 内置 agent pack
runtime SHALL 随附一个分层的内置 agent contract，其中 core agent pack SHALL 至少包括 `main-router` 与 `general-purpose`，`runtime-devtools` MAY ship specialized read-only helper agents such as `explore`、`plan` 与 `verification`，而 `runtime-planning` MAY ship official shared-planning profiles such as `planner`、`coordinator` 与 `worker`。

#### Scenario: 无自定义 agents 时启动 `runtime-core`
- **WHEN** runtime 在没有用户自定义 agents 且未安装 higher-level agent packs 的情况下启动
- **THEN** core agent pack SHALL 仍然被注册
- **AND** `main-router` SHALL 作为默认 root-agent boot path 可用于主线程执行

#### Scenario: 官方 higher-level packs 提供 specialized agents
- **WHEN** runtime 安装了提供 `explore`、`plan`、`verification`、`planner`、`coordinator` 或 `worker` 的官方 higher-level packs
- **THEN** runtime SHALL 在不改变 core agent contract 的前提下暴露这些 specialized agents
- **AND** 它们 SHALL 继续遵守同一 built-in replacement 与 visibility 规则

#### Scenario: canonical agent ownership matrix is published
- **WHEN** an embedder inspects the first-party built-in pack contract
- **THEN** the runtime SHALL publish `runtime-core` as the canonical owner of `main-router` and `general-purpose`
- **AND** SHALL publish `runtime-devtools` as the canonical owner of `explore`, `plan`, and `verification`
- **AND** SHALL publish `runtime-planning` as the canonical owner of `planner`, `coordinator`, and `worker`
