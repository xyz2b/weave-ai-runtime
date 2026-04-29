# builtin-runtime-pack Specification

## Purpose
TBD - created by archiving change python-agent-runtime-foundation. Update Purpose after archive.
## Requirements
### Requirement: 内置 tool pack
runtime SHALL 默认随附一个内置 tool pack，其中包括 `read`、`edit`、`write`、`glob`、`grep`、`bash`、`web_fetch`、`web_search`、`agent`、`skill`、`task_create`、`task_get`、`task_update`、`task_claim`、`task_release`、`task_assign_next`、`task_block`、`task_unblock`、`task_list`、`job_get`、`job_list`、`job_stop`、`ask_user` 与 `sleep`。

#### Scenario: 无自定义 tools 时启动 runtime
- **WHEN** runtime 在没有用户自定义 tools 的情况下启动
- **THEN** 内置 tool pack SHALL 仍然被注册，并根据 tool-pool resolution 规则可供 runtime 使用

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

### Requirement: Built-in task tools SHALL expose only supported task mutations
The built-in task tool surface SHALL keep raw task updates narrow, SHALL expose ownership and dependency changes only through dedicated orchestration tools, and SHALL expose retirement through dedicated archival or deletion tools.

#### Scenario: built-in task update excludes orchestration fields
- **WHEN** an agent invokes built-in `task_update`
- **THEN** the runtime SHALL accept only supported non-orchestration mutable fields on that tool surface
- **AND** SHALL direct ownership and dependency changes to `task_claim`, `task_release`, `task_assign_next`, `task_block`, or `task_unblock`

#### Scenario: built-in task retirement uses dedicated tools
- **WHEN** an agent needs to retire task records from the shared task plane
- **THEN** the runtime SHALL expose dedicated built-in task retirement operations for archive, unarchive, and delete
- **AND** SHALL NOT overload `task_update` as the public retirement path

#### Scenario: built-in task retirement surfaces canonical lifecycle errors
- **WHEN** an agent invokes a built-in task retirement or mutation operation that violates archived-task lifecycle rules
- **THEN** the runtime SHALL return structured tool-visible error codes from the canonical retirement set such as `archive_requires_completed`, `delete_requires_archived`, `already_archived`, `not_archived`, or `archived_task_immutable`
- **AND** SHALL NOT collapse those retirement failures into an unqualified generic success or no-op result

### Requirement: Built-in exact task lookup SHALL be archival-aware
The built-in `task_get` surface SHALL retrieve archived tasks by exact identifier even when default list views hide archived tasks.

#### Scenario: built-in task get returns archived task by id
- **WHEN** an agent invokes built-in `task_get` for an archived task identifier
- **THEN** the runtime SHALL return that archived task snapshot
- **AND** SHALL include canonical archival fields `is_archived`, `archived_at`, and `archived_by` in the returned payload

### Requirement: Built-in task listing SHALL support archived-visibility control
The built-in `task_list` surface SHALL default to active task visibility and SHALL allow callers to request archived task visibility explicitly.

#### Scenario: built-in task list hides archived tasks by default
- **WHEN** an agent invokes built-in `task_list` without an archived-visibility override
- **THEN** the runtime SHALL return only non-archived task entries in the default list payload
- **AND** SHALL exclude archived entries from readiness summaries such as available and blocked task identifiers

#### Scenario: built-in task list can include archived tasks explicitly
- **WHEN** an agent invokes built-in `task_list` with an explicit archived-visibility override
- **THEN** the runtime SHALL include archived task entries in the returned snapshot
- **AND** SHALL preserve each task's archival markers in that payload

#### Scenario: built-in default task list suppresses hidden archived dependency ids
- **WHEN** an agent invokes built-in `task_list` without archived visibility
- **THEN** the runtime SHALL suppress `blocks` and `blocked_by` references that target archived tasks from the visible task entries
- **AND** SHALL keep the default list payload self-contained without references to hidden archived task ids

### Requirement: Built-in `team_*` tools SHALL operate on the runtime-owned team control plane
The runtime SHALL make built-in `team_create`, `team_spawn`, `team_send`, and `team_delete` resolve against the runtime-owned team control plane rather than against host-local UI state or ad hoc caller metadata.

#### Scenario: lead agent creates and uses a team through built-in tools
- **WHEN** a lead agent invokes built-in `team_create` and later `team_spawn`
- **THEN** the runtime SHALL create or reuse runtime-owned team state and teammate membership under the shared team control-plane contract
- **AND** SHALL return structured tool results that identify the created team or teammate member

#### Scenario: built-in team tools resolve against the caller's active team binding
- **WHEN** a caller invokes built-in `team_spawn`, `team_send`, or `team_delete`
- **THEN** the runtime SHALL resolve the target team from the caller's active team binding and runtime-private context
- **AND** SHALL NOT require or accept a caller-supplied `team_id` for those built-in tool contracts

#### Scenario: built-in team creation is idempotent per leader session
- **WHEN** a lead agent that already owns an active team invokes built-in `team_create` again
- **THEN** the runtime SHALL return the existing active team for that leader
- **AND** SHALL report through the structured tool result that the team was reused rather than newly created

#### Scenario: team spawn requires a unique name and agent selector
- **WHEN** a lead agent invokes built-in `team_spawn`
- **THEN** the tool contract SHALL require a unique teammate `name` and an `agent` selector
- **AND** MAY allow teammate-level execution defaults such as `cwd`, `model`, `model_route`, `permission_mode`, `isolation`, or `max_turns`
- **AND** SHALL return a structured result containing the stable runtime-owned teammate identity

#### Scenario: teammate cannot invoke leader-only lifecycle tools
- **WHEN** a caller operating as a teammate invokes built-in `team_create`, `team_spawn`, or `team_delete`
- **THEN** the runtime SHALL reject that built-in tool call as outside the teammate's lifecycle authority
- **AND** SHALL preserve the existing team state unchanged

#### Scenario: team send supports direct and broadcast routing
- **WHEN** a caller invokes built-in `team_send` with a direct recipient or broadcast target
- **THEN** the runtime SHALL route that request through the structured team message bus
- **AND** SHALL NOT require the caller to know whether the final recipient path resolves to leader ingress, teammate execution, or a host-facing side-channel

#### Scenario: public team send uses a frozen v1 addressing contract
- **WHEN** a caller invokes built-in `team_send`
- **THEN** the tool contract SHALL require `to` and `message`
- **AND** SHALL reserve `to="leader"` for the leader, `to="*"` for broadcast, and any other `to` value for teammate-name resolution inside the caller's active team
- **AND** SHALL reject public cross-team addressing in v1

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

### Requirement: Built-in runtime pack SHALL expose a typed `team_respond` tool for workflow resolution
The runtime SHALL bundle a `team_respond` tool that resolves pending team control workflows by `workflow_id` and typed response action, and SHALL derive authority from the caller's runtime team role rather than from raw control-message composition.

#### Scenario: leader resolves a pending permission workflow
- **WHEN** a leader invokes `team_respond` for a pending permission workflow with an allowed action such as `approve` or `reject`
- **THEN** the runtime SHALL record that workflow response through the runtime-owned workflow service
- **AND** SHALL return a structured tool result describing the updated workflow status and workflow identity

#### Scenario: teammate acknowledges or completes shutdown
- **WHEN** a targeted teammate invokes `team_respond` for its pending shutdown workflow with an allowed action such as `acknowledge` or `complete`
- **THEN** the runtime SHALL accept that response only if that teammate is the authorized responder for the current shutdown workflow state
- **AND** SHALL preserve the same `workflow_id` across the updated shutdown lifecycle

#### Scenario: invalid workflow response is rejected
- **WHEN** a caller invokes `team_respond` for an unknown, unauthorized, or already terminal workflow
- **THEN** the runtime SHALL reject that tool call with a structured workflow error
- **AND** SHALL leave the existing workflow state unchanged

### Requirement: Built-in `job_*` tools SHALL reflect the shared job control plane
runtime SHALL make built-in `job_get`, `job_list`, and `job_stop` operate on the shared job control plane rather than on an executor-private or `TaskManager`-shaped internal registry contract.

#### Scenario: agent inspects background work through built-in job tools
- **WHEN** an agent invokes a built-in `job_*` tool
- **THEN** runtime SHALL resolve that operation against the shared job control plane
- **AND** SHALL return generic job control information such as lifecycle state, executor kind, visibility metadata, result or error envelope, and sidecar linkage summary where applicable

#### Scenario: built-in job stop targets a visible running job
- **WHEN** an agent invokes `job_stop` for a visible running job
- **THEN** runtime SHALL route the stop request through the shared job executor contract
- **AND** SHALL NOT require the caller to know whether the underlying work is implemented as an `asyncio` task, subprocess, thread, or custom executor

### Requirement: Official built-ins SHALL be attachable through package-contributed built-in definitions
The runtime SHALL allow official first-party packages to attach owned tools, agents, and skills through package-contributed built-in definitions rather than requiring kernel-owned optional loader tables as the primary attachment contract.

#### Scenario: Higher-level first-party package contributes built-ins
- **WHEN** an official first-party package owns one or more bundled tools, agents, or skills
- **THEN** the runtime SHALL be able to register those definitions through the package-contribution path
- **AND** the package ownership of those definitions SHALL remain observable through built-in ownership metadata or equivalent diagnostics

### Requirement: Built-in package contribution SHALL preserve supported distribution semantics
The runtime SHALL preserve the current supported distribution semantics for core and higher-level first-party built-ins when moving built-in attachment to package contributions.

#### Scenario: Runtime assembles different supported distributions
- **WHEN** the runtime assembles `runtime-core`, `runtime-default`, or `runtime-full`
- **THEN** it SHALL continue to expose the built-ins owned by the selected official packages for that distribution
- **AND** moving built-in attachment behind package contributions SHALL NOT require collapsing higher-level built-ins back into `runtime-core`

### Requirement: Built-in package contribution SHALL preserve disable and replacement semantics
The runtime SHALL preserve the current ability to disable or replace official built-in definitions when moving official built-in attachment behind package contributions.

#### Scenario: Caller disables an official package-contributed built-in
- **WHEN** a caller configures one or more official built-in tools, agents, or skills as disabled
- **THEN** the runtime SHALL suppress those definitions even if they are contributed by an official package
- **AND** it SHALL preserve the remaining package-contributed definitions for the selected distribution

#### Scenario: Caller replaces an official package-contributed built-in
- **WHEN** a caller supplies a replacement definition for an official built-in owned by a selected package
- **THEN** the runtime SHALL register the replacement under the same public built-in identity
- **AND** it SHALL preserve package ownership and diagnostic visibility semantics for that replacement path or equivalent migration metadata

### Requirement: Canonical first-party built-in distributions and owners SHALL use WeaveRT package identifiers
The runtime SHALL expose WeaveRT-branded canonical identifiers for its first-party built-in distributions and built-in ownership matrix. Canonical distribution names SHALL use `weavert-core`, `weavert-default`, and `weavert-full`, and canonical built-in owner package names SHALL use `weavert-*`.

#### Scenario: Embedder inspects built-in ownership and supported distributions
- **WHEN** an embedder inspects the built-in runtime pack contract, first-party distribution list, or built-in owner metadata
- **THEN** the runtime SHALL publish `weavert-core`, `weavert-default`, and `weavert-full` as the canonical built-in distributions
- **AND** it SHALL publish canonical built-in owner package identifiers using the `weavert-*` prefix

### Requirement: Built-in runtime pack includes dedicated task orchestration tools
The runtime SHALL include first-party task orchestration tools in the built-in runtime pack for claim, release, next-task assignment, and dependency-edge maintenance.

#### Scenario: runtime boots with task orchestration tools available
- **WHEN** the runtime starts with the built-in runtime pack enabled
- **THEN** the built-in tool catalog SHALL include `task_claim`, `task_release`, `task_assign_next`, `task_block`, and `task_unblock` or equivalent first-party task orchestration tools
- **AND** those tools SHALL participate in normal tool-pool resolution rather than requiring a special built-in agent mode

#### Scenario: built-in claim tools advance status by default
- **WHEN** a caller invokes built-in `task_claim` or `task_assign_next` for unresolved work
- **THEN** the runtime SHALL claim the task through the task orchestration control plane
- **AND** SHALL advance that task to `in_progress` by default unless an explicit runtime-owned override disables state advancement

#### Scenario: generic task update does not bypass orchestration semantics
- **WHEN** a caller invokes the built-in `task_update` tool
- **THEN** the runtime SHALL reserve orchestration-critical mutations such as dependency-edge maintenance and claim-style assignment for the dedicated orchestration tools
- **AND** SHALL reject raw orchestration-field updates that would bypass those dedicated operations

#### Scenario: owner mutation migrates to claim and release tools
- **WHEN** a caller needs to assign or clear task ownership through the built-in runtime pack
- **THEN** the runtime SHALL require that caller to use `task_claim` or `task_release` rather than direct owner mutation through `task_update`
- **AND** SHALL keep dependency-edge mutation on `task_block` and `task_unblock` rather than `task_update`

