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
- `runtime.services.metadata["package_resolution"]`

## 4.5 Package Attachment Contract Changes

边界收敛之后，package 是否“真正接上 runtime”不再只看目录布局，而要看它是否走 protocol attachment：

- `RuntimePackageManifest`
- dependency-ordered assembly
- `PackageContribution`
- capability registry lookup
- host facet discovery
- lifecycle participant registration

如果你以前做过下面这些定制，迁移时应优先改到新的 contract 上：

- patch kernel-owned first-party assembler tables
- patch optional built-in loader tables
- 直接向 `RuntimeServices` 增加 package-specific 顶层字段
- 通过 ad hoc missing-method 检查推断 optional host helper 是否存在

新的首选迁移路径是：

- built-ins -> package contribution
- package-owned runtime object -> capability registry
- optional host operation -> host facet discovery
- package-owned startup / recovery / session behavior -> lifecycle participant
- local external package selection -> `RuntimeConfig.extra_package_manifests` + `RuntimeConfig.requested_packages` + `package_resolution`

当前少量 `RuntimeServices` package-specific 字段仍会保留一段时间，但它们现在只应视为 compatibility projection。
这也包括残留的 team 顶层 helper / workflow helper：canonical discovery path 已经是 capability lookup 与 host facet discovery，新的 runtime-owned primary path 不应再把这些 wrapper 当 source of truth。

external package 的迁移口径也需要一起改：

- `RuntimeConfig.extra_package_manifests` 现在只负责 local candidate admission，不再意味着该 package 会自动进入 active runtime
- admitted external manifest 会先进入 local package catalog；真正进入装配的 graph 由 selected first-party manifests、`RuntimeConfig.requested_packages` 与 bounded dependency constraints 一起 deterministic resolve
- duplicate external package names、missing dependency、conflicting constraint、incompatible candidate、cyclic dependency 都属于 resolution phase 的结构化结果，而不是继续藏在 registration side effect 里
- `package_resolution` metadata 与 `package_registration`、`package_manifests`、`package_lookup`、`core_protocol_catalog` 分开发布；raw candidate inventory 与 active resolved graph 不再混在同一个 manifest view 里
- 这次变更仍然明确不做 remote discovery、package install、publish workflow 或 Python environment package management

新的 staged exit criteria 也应明确下来：

- `SESSION_OPEN` replay 已经只通过 lifecycle participant 触发，而不是 controller special case
- post-ingress acknowledgement 已经只通过 ingress `completion_receipts` 执行，而不是 metadata key + controller branch
- runtime-owned workflow helper 已经先走 capability / host-facet lookup，再把旧 helper 当 projection
- `TaskManager` 只在 compatibility facade 里按需 materialize，而不是 runtime-owned primary path 的默认 state owner
- package-owned host egress 已经统一切到 `HostRuntime.emit_extension_event()`，并通过 namespace-aware `HostExtensionEvent` envelope 交付

当前仓库里需要优先记住的 canonical lookup key / wrapper status 也可以直接按下面核对：

- canonical capability keys
  - `runtime.team.control_plane`
  - `runtime.team.message_bus`
  - `runtime.team.workflows`
- canonical host facet key
  - `runtime.team.workflows`
- canonical extension event contract
  - `HostRuntime.emit_extension_event()`
  - `runtime.hosts.HostExtensionEvent`
  - namespace: `runtime.team`
- canonical control-plane services
  - `RuntimeServices.job_service`
  - `RuntimeServices.task_list_service`
- retained compatibility-only wrappers
  - `TaskManager`
  - `RuntimeServices.teammates`
  - `RuntimeAssembly.teammates`

已删除的 team bridge replacement matrix 则发布在：

- `runtime.services.metadata["migration"]["team_protocol_only"]["replacement_matrix"]`
- `runtime.metadata["migration"]["team_protocol_only"]["replacement_matrix"]`

这些信息现在也会直接写进：

- `runtime.services.metadata["core_protocol_catalog"]`
- `runtime.metadata["core_protocol_catalog"]`
- `runtime.services.metadata["package_resolution"]`
- `runtime.metadata["package_resolution"]`
- `runtime.services.metadata["package_lookup"]`
- `runtime.metadata["package_lookup"]`
- `runtime.services.metadata["package_service_protocols"]`
- `runtime.metadata["package_service_protocols"]`
- `runtime.services.metadata["compatibility_surfaces"]`
- `runtime.services.metadata["compatibility_boundaries"]`
- `runtime.services.metadata["protocol_only_conformance"]`

迁移时可以直接按这个分层理解：

- `core_protocol_catalog`
  - stable core protocol source of truth
  - 只覆盖 `TranscriptStore`、`JobService`、`TaskListService`、`PermissionService`、`ElicitationService`、context contributors、invocation providers、`HostRuntime`
- `package_resolution`
  - local package catalog、resolution request、resolved graph 与 structured diagnostics 的 source of truth
- `package_lookup`
  - package-specific canonical capability key、host facet key、service-family protocol key、wrapper exit criteria 的 source of truth
- `package_service_protocols`
  - privileged memory / compaction / isolation binding 的 canonical key、resolver、owner、compatibility projection metadata 的 source of truth
- `compatibility_surfaces`
  - retained compatibility helper / projection 的 source of truth
- `compatibility_boundaries`
  - raw `runtime_context` 与 `TaskManager` 剩余 whitelist / exit criteria 的 source of truth
- `protocol_only_conformance`
  - privileged-service-slot、context-authority、task-authority 与 team-bridge finding 的 source of truth

这意味着 `runtime.team.control_plane`、`runtime.team.workflows`、`TaskManager` 仍然重要，但它们不属于 stable core protocol catalog 本身；canonical package path 继续通过 capability / host facet / migration metadata 发布，而已经删除的 team bridge surface 不再继续写进 `compatibility_surfaces`。

同样，memory / compaction / isolation 这三类 package-owned privileged service 也应按下面的口径迁移：

- canonical metadata key
  - `runtime.services.metadata["package_lookup"]["canonical_service_family_protocols"]`
- canonical resolver
  - `RuntimeServices.resolve_memory_service()`
  - `RuntimeServices.resolve_compaction_service()`
  - `RuntimeServices.resolve_isolation_service()`
- detailed ownership / projection metadata
  - `runtime.services.metadata["package_service_protocols"]`
- compatibility-only projection
  - `RuntimeServices.memory`
  - `RuntimeServices.compaction`
  - `RuntimeServices.isolation`

## 4.6 Explicit Non-Goals

这次边界收敛明确不是下面这些事情：

- 不是 purity-driven microkernel rewrite
- 不是 `TaskManager` 的 flag-day removal
- 不是立即把仓库拆成 physical multi-distribution / multi-wheel packaging layout

迁移口径应理解为：

- 优先冻结新的 kernel-specific package special case
- 优先把最贵的 boundary leak 迁到 manifest / contribution / lookup seam
- 继续保留 `JobService` 作为 authoritative surface
- 继续把 `TaskManager` 当作 compatibility facade 处理
- physical package split 留到后续边界和 public contract 更稳定时再谈

## 5. Recommended Upgrade Checklist

- 如果你依赖 workspace tools，先切到 `runtime-full` 再逐步收窄
- 如果你依赖 `plan`，继续把它视为 `runtime-devtools` helper；不要把它误当成 shared planning contract 本身
- 如果你要构建 shared plan workflow，优先启用 `runtime-planning`，再围绕 `task_*` / `job_*` 与自定义 agent profile 做收窄或扩展
- 如果你暴露 hooks 给第三方，优先只承诺 stable phases + `callback`
- 如果你在 host、store、provider 侧做定制，优先通过 package-level seams 注入，而不是 patch `runtime-core`
- 如果你还在使用旧 team helper，优先按 `runtime.services.metadata["migration"]["team_protocol_only"]["replacement_matrix"]` 改到 capability、host facet 或 `HostRuntime.emit_extension_event()` 路径
- 如果你需要定位当前 runtime 的边界状态，先看 `runtime.kernel.diagnostics` 和 `runtime.services.metadata`
