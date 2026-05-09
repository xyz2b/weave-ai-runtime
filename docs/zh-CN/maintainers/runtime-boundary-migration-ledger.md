# WeaveRT Runtime 边界迁移台账

> 文档说明：这个文件仍是 runtime-boundary 变更的详细迁移台账。维护者索引请从 `docs/zh-CN/maintainers/migration-notes.md` 开始。
> 公开元数据键、能力键和协议名保持英文写法，以便直接对照代码与诊断输出。

## 入口

- 维护者迁移索引 -> `docs/zh-CN/maintainers/migration-notes.md`
- Package system -> `docs/zh-CN/architecture/package-system.md`
- Testing and observability -> `docs/zh-CN/guides/testing-and-observability.md`

## 1. 项目定位

当前一方包边界按 distribution 与角色收敛为：

- `weavert-core`
- `weavert-default`
- `weavert-full`
- capability：`weavert-memory`、`weavert-team`
- mechanism：`weavert-compaction`、`weavert-isolation`
- adapter / provider：`weavert-hosts-reference`、`weavert-stores-file`、`weavert-openai`
- profile / workflow：`weavert-devtools`、`weavert-builtin-workflows`、`weavert-planning`

规划相关变化：

- `planner` / `coordinator` / `worker` 现在由独立 `weavert-planning` package 提供
- `weavert-full` 默认组装它们；`weavert-default` 不会
- 现有只读 planning helper `plan` 仍保留在 `weavert-devtools`

## 1.5 规范 import root 边界

- `weavert` 仍是 runtime core surface
- 拆分出的 first-party families 现在使用独立 roots，如 `weavert_openai`、`weavert_memory`、`weavert_team`、`weavert_hosts_reference`
- distribution、`enabled_packages` 与 `disabled_packages` 决定这些 add-ons 是否参与 runtime assembly

典型路径迁移：

- `weavert.openai_client` -> `weavert_openai.openai_client`
- `weavert.memory.manager` -> `weavert_memory.manager`
- `weavert.hosts.reference` -> `weavert_hosts_reference`
- `weavert.team.assembly` -> `weavert_team.assembly`

## 2. Workspace / Devtools Built-ins

内置工作区工具与角色主要集中为：

- tools：`read`、`glob`、`grep`、`edit`、`write`、`bash`、`web_fetch`、`web_search`
- agents：`explore`、`plan`、`verification`

当用户没有选中 devtools 时，诊断与迁移信息主要出现在：

- `runtime_devtools_not_selected`（位于 `weavert.kernel.diagnostics`）
- `weavert.services.metadata["migration"]` 下的 `devtools`

## 2.5 Planning profile 术语

需区分：

- `plan`
- `planner`
- `coordinator`
- `worker`

迁移建议：

- 需要只读分析 helper 时，继续把 `plan` 当作 `weavert-devtools` 内置
- 需要共享 planning workflow 时，优先使用 `weavert-planning` 中的 `planner` / `coordinator` / `worker`

## 3. Hook surface 收紧

稳定公开 phases：

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

高级公开 phases：

- `UserPromptSubmit`
- `SubagentStop`
- `PreCompact`
- `PostCompact`
- `PreContextAssemble`
- `PostContextAssemble`
- `RecoveryDecision`

公开 handler kinds：

- `callback`
- `http`
- `command`
- `agent`
- `prompt`

迁移原则是：对第三方默认只承诺稳定 phases + `callback`。

## 4. First-party package ownership 变化

职责归属变化包括：

- `remember` -> `weavert-memory`
- `team_create` / `team_spawn` / `team_send` / `team_respond` / `team_delete` -> `weavert-team`
- `verify` / `debug` / `stuck` / `batch` / `simplify` -> `weavert-builtin-workflows`
- 内置默认 OpenAI live adapter -> `weavert-openai`
- reference host implementations -> `weavert-hosts-reference`
- 文件型 transcript / job / task-list / team / workflow / mailbox stores -> `weavert-stores-file`

需要特别记住的一点：

- `openai_default` 仍是默认 route 名
- 但它现在是 tool-capable Responses adapter，而不是旧的最小文本 baseline

规划方面：

- 共享 planning primitives 仍视为 `weavert-core` 拥有
- `plan` 仍视为 `weavert-devtools` 拥有
- `planner` / `coordinator` / `worker` 现在由 `weavert-planning` 拥有

相关元数据主要写入：

- `weavert.services.metadata["first_party_package_catalog"]`
- `weavert.services.metadata["official_package_catalog_provenance"]`
- `weavert.services.metadata["package_resolution"]`

## 4.5 Package attachment 契约变化

“一个 package 是否真正接入 runtime”，现在不再取决于目录布局本身，而取决于它是否走协议化接入：

- `RuntimePackageManifest`
- 依赖顺序 assembly
- `PackageContribution`
- capability registry lookup
- host facet discovery
- lifecycle participant registration

如果你以前做过下面这些定制，优先迁向新的协议边界：

- patch kernel-owned first-party assembler tables
- patch optional built-in loader tables
- 给 `RuntimeServices` 直接加 package-specific top-level fields
- 通过 ad hoc missing-method checks 推断某个 optional host-helper 是否存在

推荐替代路径：

- built-ins -> package contribution
- package-owned runtime object -> capability registry
- optional host operation -> host facet discovery
- package-owned startup / recovery / session behavior -> lifecycle participant
- 本地外部 package 选择 -> `RuntimeConfig.extra_package_manifests` + `RuntimeConfig.requested_packages` + `package_resolution`

显式变化还包括：

- `extra_package_manifests` 只负责本地候选 admission，不再代表自动进入 active runtime
- admitted manifests 会先进入本地 package catalog；真正进入 assembly 的 active graph 会按 first-party manifests、`requested_packages` 与依赖约束做确定性解析
- 重名、缺失依赖、冲突约束、不兼容候选与循环依赖都变成 resolution-phase 的结构化结果

新的 staged exit criteria 还包括：

- `SESSION_OPEN` replay 只通过 lifecycle participants 触发
- post-ingress acknowledgement 只通过 ingress `completion_receipts`
- runtime-owned workflow helpers 优先查 capability / host facets，旧 helpers 只当投影
- `TaskManager` 只在 compatibility facade 中按需 materialize
- package-owned host egress 统一走 `HostRuntime.emit_extension_event()`

## 4.6 Closure report、legacy mode 与替换矩阵

可直接查询的接口包括：

- `weavert.query_closure_report()`
- `weavert.query_compatibility_retirement()`
- `weavert.query_persistence_profile()`
- `weavert.query_isolation_readiness()`

这些查询用于回答：

- 哪个 family 已退休
- 哪个 family 只在 legacy mode 下被容忍
- 每个 family 的迁移目标是什么
- 轻量 profile 与生产导向 profile 的 durability 差异
- `worktree` 或 `remote` isolation 是否为 `ready`、`not_configured` 或 `not_available`

## 4.7 显式非目标

当前迁移明确不追求：

- 为“纯粹性”做 microkernel 重写
- 一次性移除 `TaskManager`
- 立刻把仓库拆成物理多发行版或多 wheel 布局

更务实的步骤是：

- 先冻结新的 kernel-specific package special cases
- 先把最昂贵的边界泄漏迁移到 manifest、contribution 或 lookup seams
- 继续把 `JobService` 视为权威 surface
- 把 `TaskManager` 保留为 compatibility facade

## 4.8 Invocation provider package 迁移

Provider-only package 仍然是普通 runtime package，不是新的 manifest 分类。

最小形状仍应是：

- role=`provider`
- dependency=`weavert-core`
- `PackageContribution.invocation_providers`

注册顺序保持不变：

- built-in skill baseline -> package contribution
- package 层内部再由 contribution `order`、package dependency order 与 contribution name 稳定排序

如果一个 package 需要多个 providers，请继续使用普通 `PackageContribution(invocation_providers=(...))`，不要增加新的配置旁路。

## 5. 推荐升级清单

- 如果你依赖 workspace tools，先切到 `weavert-full`，再逐步收窄表面
- 如果你依赖 `plan`，继续把它当作 `weavert-devtools` helper，而不是共享 planning contract 本身
- 如果你想构建 shared-plan workflow，先启用 `weavert-planning`，再围绕 `task_*`、`job_*` 与自定义 agent profile 收窄或扩展
- 如果你把 hooks 暴露给第三方，优先只承诺稳定 phases + `callback`
- 如果你在定制 host、store 或 provider 行为，优先通过 package-level seams 注入，而不是 patch `weavert-core`
- 如果你仍在使用旧 team helpers，先通过 `weavert.services.metadata["migration"]["team_protocol_only"]["replacement_matrix"]` 迁往 capability、host-facet 或 `HostRuntime.emit_extension_event()`
- 如果你想检查当前 runtime boundary 状态，先看 `weavert.kernel.diagnostics` 与 `weavert.services.metadata`
