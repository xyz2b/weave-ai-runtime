# Runtime 用户扩展指南

本文面向“作为本框架的使用者，想在不改内核主循环的前提下扩展能力或接入自己系统”的场景。

本文回答 3 个问题：

1. 本框架留给用户的扩展点有哪些。
2. 每个扩展点从用户视角应该怎么扩。
3. 哪些字段虽然会被解析，但当前不应该当作稳定扩展面依赖。

结论先说：

- 普通用户最应该使用的扩展点是 `tool`、`agent`、`skill`。
- 做产品接入时，最应该使用的扩展点是 `RuntimeConfig`、`HostRuntime`、`HookBus`、权限/提问控制面、模型路由。
- 做平台化时，再进入 `TranscriptStore`、`ChildRunStore`、`MemoryProvider`、`InvocationProvider`、teammate orchestration 这一层。
- 不建议把 `TurnEngine`、`SessionController`、tool orchestration 主状态机当作普通扩展点。

## 1. 先分清三层扩展面

### 1.1 第一层：能力定义层

这是最常用、最稳定、最适合普通用户的扩展层：

- `tool`
- `agent`
- `skill`

这三类能力通过 `.weavert/` 目录发现，不要求你改 runtime 内核源码。

### 1.2 第二层：控制面与接入层

这是“把 runtime 接进自己的产品或流程”的扩展层：

- `RuntimeConfig`
- `HostRuntime`
- `HookBus`
- `PermissionEngine`
- `SharedElicitationService`
- `tool_refresh_callback`
- `model_client / model_providers / model_routes`
- `extra_package_manifests / requested_packages`

### 1.3 第三层：基础设施与持久化层

这是更偏平台接入和基础设施替换的扩展层：

- `TranscriptStore`
- `ChildRunStore`
- `MemoryProvider`
- `MemoryManagerService`
- `teammate_orchestration`

## 2. 用户最常用的扩展点

### 2.1 DefinitionSourcePaths：能力投放口

框架通过 `DefinitionSourcePaths` 发现用户定义。

默认推荐目录：

```text
your-project/
└── .weavert/
    ├── tools/
    ├── agents/
    └── skills/
```

默认发现规则：

- `tools/*.py`
- `agents/*.md`
- `skills/**/SKILL.md`

如果你用：

```python
from pathlib import Path

from weavert.runtime_kernel import RuntimeConfig

config = RuntimeConfig.for_project(Path("/your/project"))
```

runtime 会自动接入：

- `~/.weavert`
- `<project>/.weavert`

用户视角怎么扩：

1. 想给所有项目复用的能力，放到 `~/.weavert`。
2. 只想给当前项目使用的能力，放到 `<project>/.weavert`。
3. 不想走默认目录时，手工构造 `RuntimeConfig.discovery_sources`。

### 2.2 Tool：最直接的可执行扩展点

`Tool` 是最直接的用户扩展能力。它适合：

- 文件扫描
- 项目规则检查
- 接外部 API
- 读写业务系统
- 触发内部服务

当前真正可执行的自定义工具，必须使用 Python module。
`.weavert/tools/` 下的 `json/yaml` file-backed tool 已经不再受支持，discovery 会直接拒绝。
Python module 也必须导出 concrete `ToolDefinition`，而不是 `dict` / mapping-style payload，并且必须提供 `execute`。

用户视角怎么扩：

1. 在 `.weavert/tools/` 下新增一个 `.py` 文件。
2. 导出 `TOOL_DEFINITION`、`TOOL` 或 `build_tool_definition()`。
3. 至少提供：
   - `name`
   - `description`
   - `input_schema`
   - `execute`
4. 需要更严格控制时，再加：
   - `validate_input`
   - `check_permissions`
   - `traits`
   - `semantics`

### 2.3 Agent：角色化 prompt + 执行策略

`Agent` 不是一个“可执行函数”，而是一个角色定义。

它的核心是：

- prompt
- 工具池限制
- skill 池限制
- permission mode
- memory scope
- isolation mode
- model route

适合场景：

- reviewer
- planner
- repo-explorer
- release-bot
- support-agent

用户视角怎么扩：

1. 在 `.weavert/agents/` 下新增一个 `.md` 文件。
2. frontmatter 写策略字段。
3. 正文写该 agent 的系统 prompt。
4. 用 `agent_name="your-agent"` 创建 session 或执行 prompt。

补充约束：

- agent frontmatter 里的 `hooks` 不属于普通 v1 扩展面；默认装配现在会直接拒绝这类 agent-owned hook authoring。
- 如果确实要继续兼容，必须显式开启 legacy compatibility family `agent_owned_hooks`。
- 正常推荐的 hook authoring surface 仍然是 skill hooks、runtime/session/turn hook API，以及 host/runtime config 注册面。

### 2.4 Package 不是目录标签，而是协议接入点

如果你准备做的不只是单个 tool / agent / skill，而是一组需要一起装配、一起拥有 runtime object 的能力，现在推荐把它理解成 package protocol attachment，而不是“在仓库里再建一个目录”。

最小判断标准是：

- 有明确的 `RuntimePackageManifest`
- 有清晰的 dependency ordering
- 通过 `PackageContribution` 返回 owned surfaces
- package-owned service 通过 capability registry 暴露
- optional host helper 通过 host facet discovery 暴露

如果这是一个本地 embedder-owned package，现在推荐的显式注册方式是
`RuntimeConfig.extra_package_manifests`：

- 接受 `RuntimePackageManifest` 实例，或解析为 manifest 的本地 entrypoint string
- runtime 会先校验 manifest shape、trust boundary 与官方 first-party reserved name；通过校验的 external manifest 会先进入 local package candidate catalog
- 当前不支持 override mode，也不会自动扫目录找 package、remote discovery、package install 或 Python environment dependency management
- external package 只有在被 `RuntimeConfig.requested_packages` 或 active resolved graph 依赖到时，才会进入 built-ins / services / runtime contribution
- 诊断、provenance 与拒绝原因会发布到 `weavert.services.metadata["package_registration"]` / `weavert.metadata["package_registration"]`；resolved graph 与 resolution diagnostics 会单独发布到 `package_resolution`

这意味着 package boundary 现在更接近：

- “能力通过什么 contract 接上 runtime”
- 而不是“代码物理上放在什么目录里”

同时要把 stable core protocol catalog 和 package capability 分开看。当前 runtime 会把 stable core protocol 单独发布到：

- `weavert.services.metadata["core_protocol_catalog"]`
- `weavert.metadata["core_protocol_catalog"]`

对扩展方最重要的是先判断自己碰到的是哪一种 seam：

- `config-owned`
  - `TranscriptStore`
  - 首选 bind path: `RuntimeConfig.transcript_store`
- `service-owned`
  - `JobService`
  - `TaskListService`
  - `PermissionService`
  - `ElicitationService`
- `registry-owned`
  - context contributors
  - invocation providers
  - 首选 bind path: `PackageContribution.context_contributors` / `PackageContribution.invocation_providers`
- `host-bound`
  - `HostRuntime`
  - 首选 bind path: `RuntimeAssembly.bind_host()`

如果一个 surface 只出现在 `package_lookup`、`migration.team_protocol_only.replacement_matrix` 或 `compatibility_surfaces` 里，而不在 `core_protocol_catalog` 里，就不要把它误当成 stable core protocol。典型例子包括 `weavert.team.*` capability、已删除的 team bridge replacement、`TaskManager` facade，以及 `HostRuntime.emit_extension_event()` 这类 package-owned host egress contract。

对扩展方的直接含义是：

- 如果只是加一个可执行能力，继续优先写 tool / agent / skill
- 如果你要同时贡献 built-ins、runtime object、host extension 或 lifecycle behavior，再考虑 package-level contribution
- 不要默认通过 patch `RuntimeServices` 顶层字段、`FIRST_PARTY_PACKAGE_SPECS` 或 kernel switch table 完成接入
- 如果你需要稳定公开的 hook 能力，优先放在 `RuntimeConfig(hooks=...)`、host/session API，或 skill frontmatter 的 `hooks` 里。

### 2.4 Skill：可复用 workflow / prompt envelope

`Skill` 比 `Agent` 更像“可复用工作流片段”。

它的核心是：

- 可注入 prompt 内容
- inline / fork 执行语义
- 工具白名单
- 可选 hook bundle
- 可选路径可见性

适合场景：

- code review 工作流
- debug checklist
- repo onboarding workflow
- release checklist
- 安全审计模板

用户视角怎么扩：

1. 在 `.weavert/skills/<slug>/SKILL.md` 下写技能内容。
2. 用 frontmatter 控制它是否：
   - 用户可主动调用
   - 模型可自动调用
   - 只在特定路径下可见
   - 以内联还是 fork 方式执行
3. 如需生命周期拦截，可以把 `hooks` 写进 skill frontmatter。

### 2.5 BuiltinPackConfig：禁用、替换、追加内置能力

如果你不是“新增能力”，而是“调整 builtin pack”，就用 `BuiltinPackConfig`。

它支持：

- 禁用 builtin tool / agent / skill
- 替换 builtin definition
- 追加额外 builtin definition

用户视角怎么扩：

1. 想禁用某个内置能力，用 `disabled_tools` / `disabled_agents` / `disabled_skills`。
2. 想替换 builtin，用 `tool_replacements` / `agent_replacements` / `skill_replacements`。
3. 想在装配层直接追加，用 `extra_tools` / `extra_agents` / `extra_skills`。

注意优先级：

```text
bundled > user > project
```

这意味着：

- 项目级同名定义不会天然覆盖 builtin。
- 真要替换 builtin，应在 Python 装配层用 `BuiltinPackConfig`。

### 2.6 三种常见 agent 组合：planning、ops、coordinator

现在 builtin pack 已把 planning task list 和 background job control 明确拆开，所以定义 agent 时最好直接按职责配 tool pool，而不是给所有 agent 一把大锤。

这里先明确一个边界，避免把“profile 命名”和“当前 bundled agent 名字”混在一起：

- 当前真正已经 bundled 的 planning helper 是 `plan`
  - 属于 `weavert-devtools`
  - 更接近只读分析 / 步骤拆解助手
- 本节使用的 `planner` / `coordinator` / `worker`
  - 已由 `weavert-planning` 作为官方 package-owned built-ins 发布
  - 在 `weavert-full` 中会自动装配；在 `weavert-default` 中仍需显式启用 `weavert-planning`

规划型 agent：

- 适合做任务拆解、状态维护、进度同步。
- 推荐只给：
  - `task_create`
  - `task_get`
  - `task_update`
  - `task_claim`
  - `task_release`
  - `task_assign_next`
  - `task_block`
  - `task_unblock`
  - `task_archive`
  - `task_unarchive`
  - `task_delete`
  - `task_list`

如果你已经给了 `task_update`，要明确它现在只适合改非 orchestration 字段。
owner、dependency edge 和 retirement 都应走专门的 task lifecycle / orchestration tools，而不是继续发 raw patch。

如果 agent 需要看历史 task 或做恢复/清理动作，再额外告诉它：

- 默认 `task_list` 只看 active work
- 需要 archived record 时用 `task_get(task_id=...)` 做 exact lookup
- 需要 archived-visible snapshot 时显式传 `include_archived=True`

运维型 agent：

- 适合做后台执行观察、停止、故障处理。
- 推荐只给：
  - `job_get`
  - `job_list`
  - `job_stop`

协调型 agent：

- 既要维护 shared plan，又要观察后台执行。
- 可以同时给：
  - `task_*`
  - `job_*`

推荐心智模型：

- `task_*` 负责 “应该做什么、做到哪了”。
- `job_*` 负责 “现在有哪些后台执行、它们跑到哪了”。

不要再把 `task` 当作后台 job 的别名写进 agent prompt 或产品文案里。

### 2.7 `task/todo` 应视为 framework primitive，而不是某个 agent 的私有能力

如果你是这套 Runtime 的接入方或扩展方，推荐把 `task/todo` 理解成 runtime 内置 control plane，再让 agent 通过 tool pool 选择是否接入。

更准确地说：

- framework core 负责：
  - `TaskListService`
  - `task_*` builtin tools
  - host `get/watch/list task list` query surface
  - derived readiness / blocker 视图
  - 可选的 task-discipline policy 与 hidden reminder sidecar
- agent/profile 负责：
  - 是否把 `task_*` 放进 tool pool
  - 何时创建任务、何时 claim / release、何时同步进度
  - planner / coordinator / worker 这类角色化 workflow

推荐心智模型：

- `task/todo` 是 runtime primitive
- `planner` / `coordinator` 只是消费这个 primitive 的官方 profile
- user-defined agent 是否参与 task workflow，由 `tools` 和 prompt 决定，而不是由 builtin agent 类型决定

这些官方 profile 现在已经收口到 `weavert-planning`，而且它们仍然应该停留在 higher-level profile / workflow 层，而不是把 `TaskListService`、`task_*`、`job_*` 从 core 移走。

对 framework author 来说，下面几条最好视为硬边界：

- 不要把 task-list workflow 绑定到某一个 builtin agent 上。
- 不要要求所有 agent 都必须维护 task list。
- 不要把 host UI、task panel、terminal 交互模型做成 runtime contract。
- 不要把 `task` 和 `job` 混成同一个 public namespace。
- 不要默认建模成“每个 agent 一份私有 todo”；默认应优先是 session / team / orchestration 共享 planning state。

如果你要给用户提供开箱即用体验，更好的方式通常不是在 core 里硬编码某种 agent 行为，而是：

- 提供一个 `planner` profile：只给 `task_*`
- 提供一个 `coordinator` profile：给 `task_* + job_*`
- 提供一个 `worker` profile：默认可不带 `task_*`

这样做的好处是：

- core 继续保持稳定的 framework contract
- agent 行为仍可由项目方自由替换
- task/todo 不会退化成某个 builtin prompt 的隐式副作用

## 3. 控制面与接入层扩展点

### 3.1 RuntimeConfig：总装配入口

`RuntimeConfig` 是几乎所有接入面的总入口。

可配置项包括：

- `working_directory`
- `discovery_sources`
- `builtins`
- `hooks`
- `host_bindings`
- `model_client`
- `model_providers`
- `model_routes`
- `default_model_route`
- `transcript_store`
- `child_run_store`
- `default_agent`
- `system_prompt`
- `permission_handler`
- `ask_user_handler`
- `tool_refresh_callback`
- `extra_package_manifests`
- `requested_packages`
- `memory_config`
- `teammate_orchestration`

用户视角怎么扩：

1. 只是本地使用时，用 `RuntimeConfig.for_project()`。
2. 需要多模型、多宿主、多能力源时，手工构造 `RuntimeConfig(...)`。
3. 需要平台级默认 hook 时，直接写 `config.hooks`。

### 3.1.1 `metadata` 里的 runtime-owned policy

除了显式字段，`RuntimeConfig.metadata` 现在还承担一部分 runtime-owned policy rollout。

当前已经落在这条 surface 上的策略至少包括：

- `task_discipline`
- `child_run_continuation`
- `delegation`

这里尤其要注意：`task_discipline` 当前应被理解为 runtime-owned control-plane policy，而不是某个 planner profile 私有 metadata。即使 `weavert-planning` 已经作为独立 planning UX 包落地，这条策略在第一阶段也更适合继续留在 core。

其中 `delegation` 是 child execution 的正式策略入口：

```python
config = RuntimeConfig.for_project(Path("/your/project"))
config.metadata.setdefault(
    "delegation",
    {
        "max_depth": 1,
        "child_result_projection": "summary",
        "summary_max_chars": 2000,
    },
)
```

当前建议把它理解为“runtime control plane policy”，而不是普通 agent/skill metadata。

它的默认语义是：

- root execution 允许创建一层 child
- delegated child 默认不能再继续 delegation
- parent-facing child result 默认走 summary-first projection

如果必须临时兼容旧式 detailed child payload，可把 `child_result_projection` 显式改成 `"detailed"`；但这只是迁移阀门，不建议当长期默认配置依赖。

### 3.2 HostRuntime：把 runtime 接进 CLI / SDK / Web UI

`HostRuntime` 是宿主侧正式边界。

它要求实现：

- `startup()`
- `ready()`
- `shutdown()`
- `request_permission()`
- `request_elicitation()`
- `current_notifications()`
- `emit_notification()`
- `emit_turn_event()`

适合场景：

- CLI
- SDK
- WebSocket shell
- IDE extension
- 企业审批面板

用户视角怎么扩：

1. 自己实现一个 host 类。
2. 用 `weavert.bind_host(host)` 绑定。
3. 在 host 里接权限弹窗、用户输入框、turn 事件回放、通知显示。

### 3.3 HookBus：稳定生命周期节点的注入面

`HookBus` 是稳定的事件型扩展总线。

stable public phase 包括：

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

advanced public phase 包括：

- `UserPromptSubmit`
- `SubagentStop`
- `PreCompact`
- `PostCompact`
- `PreContextAssemble`
- `PostContextAssemble`
- `RecoveryDecision`

可注册来源包括：

- stable public
  - runtime 级模板 hook
  - host API hook
  - session API hook
  - skill hooks
- advanced
  - turn API hook

用户视角怎么扩：

1. 想给所有 session 默认挂一个 hook，用 `weavert.register_hook(...)` 或 `RuntimeConfig(hooks=...)`。
2. 想给宿主统一挂策略，用 `bound.register_hook(...)`。
3. 想只影响当前会话，用 `session.register_hook(...)`。
4. 想只影响当前 turn，用 `session.register_turn_hook(...)`，但把它视为 advanced surface。
5. 想把 hook 随 skill 一起打包，用 skill frontmatter 的 `hooks`。

### 3.4 Sidecar / Context Contribution：请求组装前注入上下文

除了事件 hook，本框架还保留了 request 组装前的 sidecar 注入面。

当前 canonical path 分成两类：

- request-time context contributor
  - `PackageContribution.context_contributors`
- package-owned privileged control-plane service family
  - `RuntimeServices.resolve_memory_service()`
  - `RuntimeServices.resolve_compaction_service()`
  - `RuntimeServices.resolve_isolation_service()`

sidecar 可以返回：

- `prompt_fragments`
- `private_updates`
- `diagnostics`

用户视角怎么扩：

1. 如果你的逻辑本质上是“在请求发给模型前补充上下文”，优先用 `PackageContribution.context_contributors`。
2. 如果你的逻辑本质上是“在某个 phase 上拦截事件”，优先用 `HookBus`。
3. `RuntimeServices.memory`、`RuntimeServices.compaction`、`RuntimeServices.isolation` 仍保留，但它们现在只是 compatibility projection；不要把这些 slot 当成新的 source of truth。

### 3.5 Permission 与 Elicitation：交互控制面

权限和 ask-user 都已经是正式控制面。

你可以扩：

- `weavert.services.permissions`
- `weavert.services.elicitation`
- host 的 `request_permission()`
- host 的 `request_elicitation()`

用户视角怎么扩：

1. 规则审批，优先扩 `PermissionContext` + `PermissionRule`。
2. 人工审批，优先实现 host 的 `request_permission()`。
3. 表单、下拉框、多选，优先实现 host 的 `request_elicitation()`。
4. 想替换整套行为，再直接替换 `weavert.services.permissions` 或 `weavert.services.elicitation`。

### 3.6 tool_refresh_callback：动态刷新工具池

某些工具运行后，能力图可能会变化。

正式扩展点是：

- `RuntimeConfig.tool_refresh_callback`
- `weavert.services.tool_catalog`

工具内部可触发：

```python
receipt = context.refresh_capabilities.request("tool_pool", "reason")
```

适合场景：

- 登录后解锁工具
- 按项目状态动态发现工具
- 执行某个 setup 工具后刷新工具池

### 3.7 模型层：model_client / model_providers / model_routes

模型层不是固定死的。

可扩展项包括：

- `model_client`
- `model_providers`
- `model_routes`
- `default_model_route`
- route/provider 上的 `context_window_profiles`
- route 上的 `context_window_policy`

用户视角怎么扩：

1. 单模型接入时，给一个 `model_client` 就够。
2. 多模型接入时，用命名 provider + route。
3. agent 只声明 `modelRoute`，具体 provider 和模型由 runtime route 解析。

### 3.8 InvocationProvider：额外能力源

Invocation catalog 不只接 skill。

你还可以把这些能力源统一并入 invocation catalog：

- slash commands
- plugin commands
- MCP prompts
- 任意自定义 invocation source

用户视角怎么扩：

1. 把自定义 provider 包装成 ordinary provider-only runtime package，并通过 `PackageContribution.invocation_providers` 注册。
2. 最小 manifest shape 可以直接复用 `weavert.runtime_package_protocols.build_provider_only_invocation_package_manifest()`；默认 role 是 `provider`，普通 baseline dependency 是 `weavert-core`。
3. 用 `RuntimeConfig.extra_package_manifests` + `RuntimeConfig.requested_packages` 把这个 manifest 接入当前 runtime。
4. 用 `resolve_invocations()` / `visible_invocations()` / `invocation_diagnostics()` 给 UI 提供统一能力图。

```python
from weavert.invocation_catalog import StaticInvocationProvider
from weavert.runtime_kernel import RuntimeConfig, assemble_runtime
from weavert.runtime_package_protocols import build_provider_only_invocation_package_manifest

provider_manifest = build_provider_only_invocation_package_manifest(
    name="weavert-provider-only",
    provider_name="repo-commands",
    provider=StaticInvocationProvider("repo-commands", (...)),
)

weavert = assemble_runtime(
    RuntimeConfig(
        extra_package_manifests=(provider_manifest,),
        requested_packages={"weavert-provider-only"},
    )
)
```

runtime 会按固定顺序注册 provider：

- built-in skill baseline
- package contribution（再按 contribution `order`、package dependency order、contribution name 稳定排序）

如果你需要一个以上 provider，就在自定义 `PackageContribution(invocation_providers=(...))` 里继续扩展；provider-only package 本身仍然是 ordinary runtime package，而不是专门的新 taxonomy。

调试时可看：

- `weavert.services.metadata["invocation_provider_paths"]`
- `weavert.services.metadata["invocation_provider_registrations"]`

## 4. 基础设施与持久化扩展点

### 4.1 TranscriptStore：会话 transcript 持久化

`TranscriptStore` 是正式协议。

默认实现：

- `InMemoryTranscriptStore`
- `FileTranscriptStore`

用户视角怎么扩：

1. 只想本地跑，用默认内存版即可。
2. 想会话可恢复、可审计、可持久化，给 `RuntimeConfig.transcript_store` 注入自己的实现。

如果你想先判断当前 distribution 默认 durable 到什么程度，不要靠猜，直接看：

- `weavert.query_persistence_profile()`
- `weavert.services.metadata["closure_report"]["persistence_profile"]`

### 4.2 ChildRunStore：子 agent / child run 持久化

`ChildRunStore` 用于记录：

- run_id
- parent linkage
- 状态
- 终态 metadata

默认实现取决于 distribution：

- `weavert-core` / `weavert-default`：默认是内存版
- `weavert-full`：默认绑定 first-party durable file-backed child-run store

用户视角怎么扩：

1. 不关心 child run durable history 时，可以不管。
2. 想保留 background/fork run 历史时，实现自己的 `ChildRunStore`。

和 transcript 一样，想确认当前 assembly 默认 contract 时，优先看 `persistence_profile`，不要只看某个类名。

要注意：`ChildRunStore` 解决的是 durable history，不是 wake-up policy。
waiting parent session 被 terminal child run 唤醒，是 runtime continuation bridge 的职责；typed `CHILD_RUN` event 仍然是观测真相。

还要注意一层新的 contract 分离：

- parent-facing `agent` / forked `skill` result 现在默认只返回 summary-first child projection
- 完整 child `messages[]` 不再默认复制回 parent tool result
- 如果你需要 full child history，应读取 `ChildRunStore`、`AgentRunRecord`、host child-run query/watch surface，或消费 typed `CHILD_RUN` event

也就是说：

- `ChildRunStore` / `CHILD_RUN` 负责 truth
- parent-facing child result 负责低噪声反馈
- continuation ingress 现在携带的是 summary-aware child completion payload，而不是另一份完整 child transcript

### 4.3 MemoryConfig：声明式调整记忆行为

你可以通过两种方式调 memory：

- `RuntimeConfig.memory_config`
- `.weavert/memory/config.yaml`

可调项包括：

- retrieval 数量和偏好
- extraction 策略
- session refresh 阈值
- consolidation cadence

### 4.4 MemoryProvider / MemoryManagerService：替换记忆后端

Memory 默认是 file-backed。

但框架也保留了：

- `MemoryProvider` 协议
- `LongTermMemory`
- `LongTermMemoryService`

需要注意：

- 当前没有 `RuntimeConfig.memory_provider` 这样的直接配置槽位。
- 如果你想替换 `MemoryProvider`，最实际的接法是先 `assemble_runtime()`，再替换 `weavert.services.memory`。

### 4.5 teammate_orchestration：持久协作 agent 壳

如果你要的是“长期存在、可心跳、可重试、可恢复”的协作 agent，而不是一次性 subagent，那么应看 `teammate_orchestration`。

配置项包括：

- `enabled`
- `mailbox_root`
- `claim_lease_ms`
- `heartbeat_interval_ms`
- `retry_max_attempts`
- `retry_backoff_ms`

## 5. 当前不建议用户强依赖的点

下面这些字段或模型当前会被解析，但不应当作稳定扩展面重度依赖：

- `AgentDefinition.hooks`
- `AgentDefinition.initial_prompt`
- `AgentDefinition.critical_system_reminder`
- `AgentDefinition.mcp_servers`
- `ToolDefinition.prompt`
- 用户自定义 tool 的 `runtime_execution_class="privileged"`

另外，下面这些字段当前更偏描述性 metadata，而不是执行主路径的核心依赖：

- `ToolDefinition.output_schema`
- `ToolDefinition.search_hint`

如果你要做稳定接入，优先围绕这些字段构建：

- tool: `input_schema` / `validate_input` / `check_permissions` / `execute`
- agent: `tools` / `disallowed_tools` / `skills` / `permission_mode` / `memory` / `isolation` / `model_route`
- skill: `execution_context` / `allowed_tools` / `hooks` / `paths`

## 6. 最小扩展示例

下面给出 5 个从用户视角最常见的最小样例。

### 6.1 示例一：新增一个可执行自定义 Tool

文件：

```text
.weavert/tools/check_file.py
```

代码：

```python
from weavert import ToolDefinition, ToolTraits


async def execute(tool_input, context):
    path = context.cwd / tool_input["file_name"]
    return {
        "file_name": tool_input["file_name"],
        "exists": path.exists(),
        "session_id": context.session_id,
        "turn_id": context.turn_id,
    }


TOOL_DEFINITION = ToolDefinition(
    name="check_file",
    description="Check whether a file exists under the current cwd.",
    input_schema={
        "type": "object",
        "properties": {
            "file_name": {"type": "string"},
        },
        "required": ["file_name"],
        "additionalProperties": False,
    },
    traits=ToolTraits(
        read_only=True,
        concurrency_safe=True,
    ),
    execute=execute,
)
```

如何接入：

```python
from pathlib import Path

from weavert.runtime_kernel import RuntimeConfig, assemble_runtime

config = RuntimeConfig.for_project(Path("/your/project"))
config.model_client = my_model_client

weavert = assemble_runtime(config)
```

适用建议：

- 查询型工具尽量声明 `read_only=True`。
- 真正有副作用的工具再配 `check_permissions`。

### 6.2 示例二：新增一个项目级 Agent

文件：

```text
.weavert/agents/reviewer.md
```

内容：

```md
---
name: reviewer
description: Review code changes and focus on bugs, regressions, and missing tests.
tools:
  - read
  - glob
  - grep
skills:
  - verify
permissionMode: default
memory: project
isolation: none
modelRoute: review
---

You are a code review agent.
Prioritize correctness, regression risk, and missing validation.
Prefer concise findings with concrete evidence.
```

如何调用：

```python
messages = await weavert.run_prompt(
    "Review the current changes.",
    session_id="review-session",
    agent_name="reviewer",
)
```

适用建议：

- `tools` 和 `skills` 用来收窄能力面。
- `modelRoute` 用来把不同 agent 路由到不同模型。
- `memory` 和 `permissionMode` 是策略，不是提示词。

### 6.3 示例三：新增一个带 Hook 的 Skill

文件：

```text
.weavert/skills/review-python/SKILL.md
```

内容：

```md
---
name: Python Review
description: Review Python changes with a conservative workflow.
context: inline
allowed-tools:
  - read
  - glob
  - grep
paths:
  - "**/*.py"
hooks:
  PreToolUse:
    matcher: bash
    effect:
      continue_execution: false
      notifications:
        - "review-python skill blocks bash; use read/glob/grep instead."
---

Review only Python files that are relevant to the current task.
Focus on:

- behavioral regressions
- missing tests
- risky edits near permissions, state, and I/O

If no issue is found, say so explicitly.
```

说明：

- `context: inline` 表示 skill 内容会以内联 system message 注入。
- `allowed-tools` 会收窄该 skill 的工具池。
- `hooks` 会随 skill 一起注册到 `HookBus`。
- `paths` 会让这个 skill 只在 Python 相关上下文下可见。

### 6.4 示例四：接入一个自定义 Host

代码：

```python
from pathlib import Path

from weavert import PermissionBehavior, PermissionOutcome
from weavert.elicitation import ElicitationResponse
from weavert.hosts import HostRuntime
from weavert.runtime_kernel import RuntimeConfig, assemble_runtime


class MyHost:
    name = "my-host"

    async def startup(self) -> None:
        return None

    async def ready(self) -> None:
        return None

    async def shutdown(self) -> None:
        return None

    async def request_permission(self, request):
        approved = request.name in {"read", "glob", "grep"}
        return PermissionOutcome(
            behavior=PermissionBehavior.ALLOW if approved else PermissionBehavior.DENY,
            message=request.message,
            updated_input=dict(request.payload),
            details={"approved": approved, "host": self.name},
            source="host",
        )

    async def request_elicitation(self, request):
        return ElicitationResponse(response="yes", source="host")

    def current_notifications(self):
        return ()

    async def emit_notification(self, message) -> None:
        print(f"[notify] {message.text}")

    async def emit_turn_event(self, session_id, event) -> None:
        print(f"[event] {session_id} {event.event_type.value}")


config = RuntimeConfig.for_project(Path("/your/project"))
config.model_client = my_model_client

weavert = assemble_runtime(config)

async with weavert.bind_host(MyHost()) as bound:
    async for event in bound.stream_prompt(
        "Check the workspace for risky edits.",
        session_id="host-demo",
    ):
        pass
```

适用建议：

- CLI、Web UI、IDE extension 都应优先走 host，而不是自己套一层主循环。
- 权限确认、表单提问、turn event 输出都应走 host 正式接口。

### 6.5 示例五：替换 TranscriptStore 和 MemoryProvider

#### 6.5.1 替换 TranscriptStore

代码：

```python
from pathlib import Path

from weavert.runtime_kernel import RuntimeConfig, assemble_runtime
from weavert.session_runtime import FileTranscriptStore

project_root = Path("/your/project")

config = RuntimeConfig.for_project(project_root)
config.model_client = my_model_client
config.transcript_store = FileTranscriptStore(
    project_root / ".weavert" / "transcripts"
)

weavert = assemble_runtime(config)
```

说明：

- `TranscriptStore` 可以直接通过 `RuntimeConfig.transcript_store` 注入。
- 如果你要落数据库，也应实现同一协议后注入这里。

#### 6.5.2 替换 MemoryProvider

当前没有 `RuntimeConfig.memory_provider` 这样的直接字段。

最小接法是：

1. 先装配 runtime。
2. 再替换 `weavert.services.memory`。
3. 最好在创建 session 之前完成替换。

代码：

```python
from pathlib import Path

from weavert.definitions import MemoryScope
from weavert.memory import (
    LongTermMemoryService,
    MemoryDocument,
    MemoryEntry,
    MemoryProvider,
)
from weavert.runtime_kernel import RuntimeConfig, assemble_runtime


class InMemoryMemoryProvider:
    def __init__(self) -> None:
        self._docs = {}

    def prepare_context(self, context) -> None:
        self._docs.setdefault(str(context.memory_root), [])

    def load_entrypoint(self, context):
        return None

    def load_long_term_manifest(self, context):
        return {"entries": []}

    def list_documents(self, context):
        return tuple(self._docs.get(str(context.memory_root), ()))

    def materialize_documents(self, context, relative_paths):
        docs = self._docs.get(str(context.memory_root), ())
        selected = [
            doc
            for doc in docs
            if any(doc.path.name == Path(path).name for path in relative_paths)
        ]
        return tuple(selected)

    def persist_entries(self, context, entries):
        docs = self._docs.setdefault(str(context.memory_root), [])
        persisted = []
        for index, entry in enumerate(entries, start=1):
            doc = MemoryDocument(
                scope=context.scope,
                path=context.memory_root / f"in-memory-{index}.md",
                title=entry.title,
                content=entry.content,
                kind="document",
                metadata=dict(entry.metadata),
            )
            docs.append(doc)
            persisted.append(doc)
        return tuple(persisted)

    def update_document(self, context, document, *, title=None, content=None, metadata_updates=None):
        updated = MemoryDocument(
            scope=document.scope,
            path=document.path,
            title=title or document.title,
            content=content or document.content,
            kind=document.kind,
            metadata={**document.metadata, **dict(metadata_updates or {})},
        )
        docs = self._docs.setdefault(str(context.memory_root), [])
        for index, existing in enumerate(docs):
            if existing.path == document.path:
                docs[index] = updated
                return updated
        return None


project_root = Path("/your/project")

config = RuntimeConfig.for_project(project_root)
config.model_client = my_model_client

weavert = assemble_runtime(config)
weavert.services.memory = LongTermMemoryService(
    provider=InMemoryMemoryProvider(),
    project_root=project_root,
    memory_config=config.memory_config,
)
```

说明：

- `TranscriptStore` 可以在装配前通过 config 注入。
- `MemoryProvider` 当前更适合在装配后替换 `weavert.services.memory`。
- 如果你已经有自定义 `LongTermMemory` 实例，也可以直接传 `manager=...` 给 `LongTermMemoryService`。

## 7. 从用户目标倒推扩展方式

如果你的目标是下面这些，优先选对应扩展面：

```text
我想加一个新能力
  -> Tool / Agent / Skill

我想限制某个 Agent 能用什么
  -> AgentDefinition.tools / disallowedTools / skills

我想限制某个 Skill 在什么上下文可见
  -> SkillDefinition.paths

我想接入审批或 UI 提问
  -> HostRuntime / PermissionEngine / ElicitationService

我想在某个生命周期节点插入逻辑
  -> HookBus

我想在模型请求发出前补上下文
  -> RuntimeServices.hooks.collect()

我想按上下文动态刷新工具池
  -> tool_refresh_callback

我想做多模型路由
  -> model_providers + model_routes + default_model_route

我想把 slash / plugin / MCP prompt 也纳入统一能力图
  -> build_provider_only_invocation_package_manifest() / PackageContribution.invocation_providers / RuntimeConfig.extra_package_manifests + requested_packages

我想持久化 transcript
  -> TranscriptStore

我想持久化 child runs
  -> ChildRunStore

我想检查当前 runtime 还剩哪些 legacy / durability / isolation gap
  -> `weavert.query_closure_report()` / `weavert.query_persistence_profile()` / `weavert.query_isolation_readiness()`

我想替换记忆后端
  -> MemoryProvider + LongTermMemoryService

我想做持久协作 agent
  -> teammate_orchestration
```

## 8. 推荐实践

1. 先从 `.weavert/tools`、`.weavert/agents`、`.weavert/skills` 扩展，不要一上来改 runtime 内核。
2. 需要产品接入时，优先用 `bind_host()`，不要自己重写 session/turn 循环。
3. 想插入业务控制逻辑时，优先用 `HookBus` 或 sidecar collect，而不是改 `TurnEngine`。
4. 想替换 builtin，不要赌同名覆盖，直接用 `BuiltinPackConfig`。
5. 想替换 memory provider 时，记住当前没有 `RuntimeConfig.memory_provider`，应替换 `weavert.services.memory`。

## 9. 相关文档

- `docs/weavert-integration-guide.md`
- `docs/weavert-definition-authoring-guide.md`
- `docs/weavert-control-plane-extension-guide.md`
- `docs/weavert-hook-configuration-platform.md`
- `docs/current-system-architecture.md`
