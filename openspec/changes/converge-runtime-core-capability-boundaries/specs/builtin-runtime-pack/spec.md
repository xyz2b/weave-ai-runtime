## MODIFIED Requirements

### Requirement: 内置 tool pack
runtime SHALL 默认定义一个分层的内置 tool pack contract，其中 core pack 负责 runtime-generic boot 与 control-plane tooling，optional first-party packs 可以额外提供 workspace-oriented 或 team-oriented tools。core pack SHALL 至少包括 `agent`、`skill`、`ask_user`、`sleep`、`task_create`、`task_get`、`task_update`、`task_claim`、`task_release`、`task_assign_next`、`task_block`、`task_unblock`、`task_archive`、`task_unarchive`、`task_delete`、`task_list`、`job_get`、`job_list` 与 `job_stop`。workspace-oriented tools such as `read`、`glob`、`grep`、`edit`、`write`、`bash`、`web_fetch`、`web_search` SHALL be allowed to ship in an official higher-level pack rather than inside `runtime-core`。team-oriented tools such as `team_create`、`team_spawn`、`team_send`、`team_respond` 与 `team_delete` SHALL be allowed to ship with the official team capability package rather than the core pack.

#### Scenario: 仅安装 core built-in pack 启动 runtime
- **WHEN** runtime 在没有 optional workspace pack 或 team pack 的情况下启动
- **THEN** core built-in tools SHALL 仍然被注册，并根据 tool-pool resolution 规则可供 runtime 使用
- **AND** runtime-core 的一致性 SHALL NOT 依赖 file、shell、web 或 team-specific tools 同时存在

#### Scenario: `runtime-full` 暴露额外 built-in packs
- **WHEN** runtime 以 `runtime-full` 启动
- **THEN** runtime SHALL 在 core built-in pack 之外同时暴露已安装的 workspace-oriented 与 team-oriented first-party packs
- **AND** tool-pool resolution SHALL 对这些 pack 适用同一 built-in definition contract

#### Scenario: canonical tool ownership matrix is published
- **WHEN** an embedder inspects the first-party built-in pack contract
- **THEN** the runtime SHALL publish `runtime-core`, `runtime-team`, and `runtime-devtools` as the canonical default owners for their respective built-in tool sets
- **AND** SHALL document that ownership matrix explicitly rather than leaving tool ownership as an implementation detail

### Requirement: 内置 agent pack
runtime SHALL 随附一个分层的内置 agent contract，其中 core agent pack SHALL 至少包括 `main-router` 与 `general-purpose`，而 specialized first-party agents such as `explore`、`plan` 与 `verification` MAY ship in an official higher-level pack rather than in `runtime-core`.

#### Scenario: 无自定义 agents 时启动 `runtime-core`
- **WHEN** runtime 在没有用户自定义 agents 且未安装 higher-level agent packs 的情况下启动
- **THEN** core agent pack SHALL 仍然被注册
- **AND** `main-router` SHALL 作为默认 root-agent boot path 可用于主线程执行

#### Scenario: 官方 higher-level pack 提供 specialized agents
- **WHEN** runtime 安装了提供 `explore`、`plan` 或 `verification` 的官方 higher-level pack
- **THEN** runtime SHALL 在不改变 core agent contract 的前提下暴露这些 specialized agents
- **AND** 它们 SHALL 继续遵守同一 built-in replacement 与 visibility 规则

#### Scenario: canonical agent ownership matrix is published
- **WHEN** an embedder inspects the first-party built-in pack contract
- **THEN** the runtime SHALL publish `runtime-core` as the canonical owner of `main-router` and `general-purpose`
- **AND** SHALL publish `runtime-devtools` as the canonical owner of `explore`, `plan`, and `verification`

### Requirement: 内置 skill pack
runtime SHALL 支持由 core pack 与 official higher-level packs 共同提供 first-party skills。官方支持的 `runtime-default` / `runtime-full` 分发组合 SHALL 继续提供 `remember`、`verify`、`debug`、`stuck`、`batch` 与 `simplify` 这些 first-party skills，但 runtime SHALL NOT 要求它们必须全部位于 `runtime-core` 包内。

#### Scenario: `runtime-default` 暴露 first-party memory skill
- **WHEN** runtime 以 `runtime-default` 启动且没有用户自定义 skills
- **THEN** `remember` SHALL 仍然按 skill discovery 与 activation 规则在 session 中可用
- **AND** runtime SHALL 允许该 skill 来自 `runtime-memory` 而不是 `runtime-core`

#### Scenario: `runtime-full` 暴露完整 first-party skill 集
- **WHEN** runtime 以 `runtime-full` 启动且没有用户自定义 skills
- **THEN** `remember`、`verify`、`debug`、`stuck`、`batch` 与 `simplify` SHALL 仍然按 skill discovery 与 activation 规则在 session 中可用
- **AND** runtime SHALL 允许它们分别来自 `runtime-memory` 与 `runtime-builtin-workflows`

#### Scenario: `runtime-core` 不强制携带所有 first-party skills
- **WHEN** 仅组装 `runtime-core` 而未安装 higher-level first-party skill packs
- **THEN** runtime-core SHALL 仍然保持可启动
- **AND** SHALL NOT 因缺少 non-core first-party skills 而破坏 root runtime boot contract

#### Scenario: canonical skill ownership matrix is published
- **WHEN** an embedder inspects the first-party built-in pack contract
- **THEN** the runtime SHALL publish `runtime-builtin-workflows` as the canonical owner of `verify`, `debug`, `stuck`, `batch`, and `simplify`
- **AND** SHALL publish `runtime-memory` as the canonical owner of `remember`

## ADDED Requirements

### Requirement: Built-in `main-router` remains the default boot path and is replaceable
runtime SHALL keep the bundled `main-router` on the default runnable boot path, and SHALL allow hosts or embedders to replace that bundled definition through the documented built-in replacement contract rather than by mutating kernel internals.

#### Scenario: runtime boots with the bundled `main-router`
- **WHEN** runtime starts without an explicit root-agent override
- **THEN** `main-router` SHALL be the default root routing agent used for main-thread execution
- **AND** runtime SHALL keep the same root-agent boot semantics regardless of whether optional higher-level packs are installed

#### Scenario: embedder replaces bundled `main-router`
- **WHEN** an embedder supplies a built-in replacement for `main-router`
- **THEN** runtime SHALL use that replacement as the root-agent definition
- **AND** SHALL NOT require private patching of runtime internals to make the replacement effective
