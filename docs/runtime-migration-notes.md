# Runtime Boundary Migration Notes

本文档汇总 runtime 边界收敛后的迁移重点，适合已经基于旧默认 built-ins、旧 hook 面，或旧 first-party 包布局接入的用户快速核对。

## 1. 项目定位

这套项目现在明确定位为 **general AI runtime framework**，而不是 Claude Code parity effort。

推荐把它理解为三层装配体系：

- `runtime-core`
- `runtime-default`
- `runtime-full`

以及四类 first-party 包角色：

- capability：`runtime-memory`、`runtime-team`
- mechanism：`runtime-compaction`、`runtime-isolation`
- adapter / provider：`runtime-hosts-reference`、`runtime-stores-file`、`runtime-openai`
- profile / workflow：`runtime-devtools`、`runtime-builtin-workflows`、`runtime-planning`

当前还需要额外记住一条事实：

- `planner` / `coordinator` / `worker` 已经由独立 `runtime-planning` 包发布
- `runtime-full` 会自动装配它们，`runtime-default` 不会
- 现有的只读 planning helper `plan` 仍然保留在 `runtime-devtools`

## 2. Workspace / Devtools Built-ins

旧版本里经常被当作“默认总会在”的 workspace-oriented tools 和 coding agents，现在归到 `runtime-devtools`，并且只会在 `runtime-full` 中自动启用。

受影响的 built-ins 包括：

- tools：`read`、`glob`、`grep`、`edit`、`write`、`bash`、`web_fetch`、`web_search`
- agents：`explore`、`plan`、`verification`

如果你之前默认依赖这些 built-ins，有两种兼容路径：

1. 直接使用 `RuntimeDistribution.FULL`
2. 保持现有 distribution，但显式启用 `runtime-devtools`

运行时现在会提供两类迁移线索：

- `runtime.kernel.diagnostics` 中的 `runtime_devtools_not_selected`
- `runtime.services.metadata["migration"]` 中的 `devtools` 条目

## 2.5 Planning Profile Terminology

当前最容易混淆的不是 task/job contract，而是 planning profile 命名。

请按下面的口径理解：

- `plan`
  - 当前 bundled 且可直接发现的 agent
  - 属于 `runtime-devtools`
  - 更接近只读分析、执行步骤拆解、实现前规划助手
- `planner`
  - `runtime-planning` 中的官方 shared task-list 维护 profile
- `coordinator`
  - `runtime-planning` 中的官方 `task_* + job_*` 协调 profile
- `worker`
  - `runtime-planning` 中的官方执行型 profile
  - 默认不拥有 shared task list，也不会自动拿到 optional devtools 或 team 工具

这意味着：

- 现在没有“从旧 `plan` 自动迁移到某个已落地 `planner` 包”的硬迁移步骤
- 需要只读分析 helper 时，继续把 `plan` 当作 `runtime-devtools` built-in 看待
- 需要 shared plan workflow 时，优先使用 `runtime-planning` 提供的 `planner` / `coordinator` / `worker`，再按需要做 agent replacement 或 project override

## 3. Hook Surface Tightening

稳定 public hook phase 现在只保留 ordinary-v1 范围：

- `SessionStart`
- `SessionEnd`
- `PreToolUse`
- `PostToolUse`
- `PostToolUseFailure`
- `PreModelRequest`
- `PostModelResponse`
- `Stop`
- `Notification`
- `Elicitation`
- `ElicitationResult`

以下 phase 继续存在，但应视为 advanced contract，而不是普通平台可移植承诺：

- `UserPromptSubmit`
- `SubagentStop`
- `PreCompact`
- `PostCompact`
- `PreContextAssemble`
- `PostContextAssemble`
- `RecoveryDecision`

稳定 public handler kind 现在只有：

- `callback`

以下 handler kinds 仅作为 advanced 或 package-specific surface 对待：

- `http`
- `command`
- `agent`
- `prompt`

这些结构化信息也会通过 `runtime.services.metadata["migration"]["hook_contract"]` 暴露。

## 4. First-Party Package Ownership Changes

以下能力所有权现在应按 package 来理解，而不是按 kernel 内部文件布局理解：

- `remember` -> `runtime-memory`
- `team_create` / `team_spawn` / `team_send` / `team_respond` / `team_delete` -> `runtime-team`
- `verify` / `debug` / `stuck` / `batch` / `simplify` -> `runtime-builtin-workflows`
- bundled OpenAI baseline -> `runtime-openai`
- reference host implementations -> `runtime-hosts-reference`
- file-backed transcript / job / task-list / team / workflow / mailbox stores -> `runtime-stores-file`

关于 planning 这一块，当前 package ownership 已经显式落地：

- shared planning primitive 仍应理解为 `runtime-core` 所有
- `plan` 仍应理解为 `runtime-devtools` 所有
- `planner` / `coordinator` / `worker` 现在由 `runtime-planning` 所有

运行时会把当前已选 package 和其 builtin 所有权摘要写进：

- `runtime.services.metadata["first_party_package_catalog"]`

## 5. Recommended Upgrade Checklist

- 如果你依赖 workspace tools，先切到 `runtime-full` 再逐步收窄
- 如果你依赖 `plan`，继续把它视为 `runtime-devtools` helper；不要把它误当成 shared planning contract 本身
- 如果你要构建 shared plan workflow，优先启用 `runtime-planning`，再围绕 `task_*` / `job_*` 与自定义 agent profile 做收窄或扩展
- 如果你暴露 hooks 给第三方，优先只承诺 stable phases + `callback`
- 如果你在 host、store、provider 侧做定制，优先通过 package-level seams 注入，而不是 patch `runtime-core`
- 如果你需要定位当前 runtime 的边界状态，先看 `runtime.kernel.diagnostics` 和 `runtime.services.metadata`
