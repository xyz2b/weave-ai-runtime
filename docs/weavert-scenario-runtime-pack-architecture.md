# Scenario Runtime Pack Architecture

本文档给出官方 scenario runtime pack 架构说明，用来回答下面几个容易混淆的问题：

- runtime distribution 和 scenario pack 到底是什么关系
- 哪些东西应该放在 shared package，哪些应该放在 scenario pack
- app-owned wiring、host integration、permission-policy composition 的边界在哪里
- coding / chat / local assistant 三种产品形态，应该怎样在同一套 runtime package contract 上组合出来

结论先说：

- distribution 仍然是 coarse-grained first-party baseline
- scenario pack 是 product-profile layer
- shared package 负责可复用 capability surface
- app-owned wiring 负责 provider、store、host、final permission composition
- host 仍然是 host bridge 的 owner
- 最终 permission posture 仍然由应用决定，而不是由 scenario pack 强制接管

## 1. Five-layer mental model

```text
Runtime distribution
  -> first-party baseline selection

Shared packages
  -> retrieval / web / browser / local OS / PIM / other reusable bridges

Scenario pack
  -> product-profile defaults, packaging guidance, visibility posture

App-owned wiring
  -> provider selection, store selection, selected first-party packages,
     external package admission, host binding, final permission composition

Host + permission control plane
  -> deployment-specific mediation, approval UX, audit sinks, risk posture
```

最重要的约束是：

- scenario pack 可以推荐 baseline posture
- scenario pack 可以依赖 shared package
- scenario pack 可以通过普通 package metadata、package-owned context contributor 和 profile-specific diagnostics 公开 profile guidance
- scenario pack 不应冒充 host bridge
- scenario pack 不应成为 final permission engine
- scenario pack 不应吞掉 provider / store / deployment wiring authority

## 2. Ownership matrix

| Layer | Owns | Should not own |
| --- | --- | --- |
| distribution | `weavert-core/default/full` 这种 coarse baseline | product-specific host policy |
| shared package | retrieval, web, browser, local-OS, PIM 之类复用 capability | 某一个产品形态的全部 workflow 语义 |
| scenario pack | product-profile defaults, shared-package composition, expected tool/agent/skill posture | final host binding, mandatory provider selection, final permission composition |
| app-owned wiring | selected first-party packages, `extra_package_manifests`, `requested_packages`, provider routes, stores, host binding | reusable low-level bridge implementation |
| host / permission plane | approval UX, audit, deployment policy, live host mediation | repo-level reusable package catalog |

换句话说：

- shared package 解的是 "这个 capability surface 复不复用"
- scenario pack 解的是 "这个产品 profile 默认长什么样"
- app wiring 解的是 "这个部署最终接了哪些 provider / store / host / policy"

## 3. Scenario packs do not replace distributions or `.weavert/`

三类东西都保留，而且职责不同：

### 3.1 Distribution

distribution 继续回答：

- 先拿哪组官方 first-party baseline
- 默认有哪些 first-party package 已经在 graph 里

### 3.2 Scenario pack

scenario pack 继续回答：

- 这是 coding、chat 还是 local assistant
- 这个 profile 期望哪些 first-party package 被启用
- 这个 profile 期望依赖哪些 shared package
- 这个 profile 的默认边界是什么

在当前 contract 里，scenario pack 仍然通过现有 package-selection surfaces 激活：

- `RuntimeConfig.distribution`
- `RuntimeConfig.enabled_packages` / `RuntimeConfig.disabled_packages`
- `RuntimeConfig.extra_package_manifests`
- `RuntimeConfig.requested_packages`

它们不属于任何默认 distribution baseline；如果不显式通过 external/optional package path 接入，
默认 runtime 不会自动装入这些 shared package 或 scenario pack。

它不是一套新的 kernel API。

### 3.3 Workspace-local `.weavert/`

`.weavert/` 继续回答：

- 当前 workspace 自己的 tool / agent / skill 定义是什么
- 哪些能力只想在这个项目里出现
- 哪些产品 profile 上，还要再叠加 project-local behavior

因此正确关系是：

- distribution = coarse baseline
- scenario pack = product profile
- `.weavert/` = workspace-local authoring layer

场景上完全可以这样叠加：

1. 先选一个 coding/chat/local-assistant reference scenario pack
2. 再在项目的 `.weavert/` 里加 repo-specific tool / skill
3. 最后由应用自己绑定 host、provider、store 和 permission policy

## 4. Reference shared package shapes

当前仓库提供一组 manifest-backed reference shared package shape，代码在
`packages/core/src/weavert/scenario_runtime_packs.py`：

- `weavert-shared-retrieval`
  - retrieval-oriented shared package example
  - 暴露 `retrieve_context` / `prepare_citations`
  - 适合 chat / local assistant 复用
- `weavert-bridge-web`
  - read-only web / HTTP grounding surface
  - 暴露 `grounding_web_search` / `grounding_web_fetch`
- `weavert-bridge-browser`
  - browser bridge surface
  - 暴露 `browser_snapshot` / `browser_stage_navigation` / `browser_stage_interaction`
  - 只发布 staged inspection / action receipt，不接管最终 browser host
- `weavert-bridge-local-os`
  - local OS bridge surface
  - 暴露 `local_os_snapshot` / `local_os_stage_file_change` /
    `local_os_stage_process_launch` / `local_os_stage_notification`
  - 适合把 file / process / notification capability 保持在 shared package，而不是塞进 assistant profile
- `weavert-bridge-pim`
  - PIM bridge surface
  - 暴露 `pim_list_agenda` / `pim_lookup_contacts` / `pim_stage_calendar_event` /
    `pim_stage_reminder` / `pim_stage_task`
  - 明确 calendar / reminder / contact / task surface 可以 shared reuse，同时把最终 account binding 留给应用
- `weavert-shared-git`
  - coding-oriented shared git inspection surface
- `weavert-shared-workspace-intelligence`
  - coding-oriented shared symbol / reference / outline / test-target surface

这些 shared package 现在都通过 ordinary manifest-backed `shared-package` pattern 表达，目的不是把它们产品化，而是明确：

- retrieval 不应该被塞进每一个 scenario pack 私有实现里
- browser / local OS / PIM bridge 不应该在每个 assistant profile 里重复实现
- git inspection / workspace intelligence 不应该继续只靠 demo-local shell 约定
- scenario pack 应该组合它们，而不是吸收它们的所有权

同时这组 reference shared package 现在也演示 canonical shared-package surface contract：

- runtime-resolved
  - `package_candidate`
- projected + convention-only
  - `shared_surface_family`
  - `intended_profiles`
  - `tool_ids` / `agent_ids` / `skill_ids`
  - `shared_surfaces`

也就是说，shared package 仍然走 ordinary runtime package contract，但会额外发布一层
family-specific metadata vocabulary，供 caller 安全 inspect，而不是逼应用再发明自己的字段名。
更完整的 authoring 约定见 `docs/weavert-user-extension-guide.md`。

## 5. Reference scenario pack shapes

### 5.1 Coding pack

reference package:

- `weavert-scenario-coding`

recommended first-party packages:

- `weavert-devtools`
- `weavert-planning`
- `weavert-builtin-workflows`

shared-package dependencies:

- `weavert-shared-git`
- `weavert-shared-workspace-intelligence`

expected profile tools / agents / skills
(after recommended first-party packages are enabled):

- tools:
  - baseline first-party: `read`, `glob`, `grep`, `edit`, `write`, `bash`
  - workflow control: `agent`, `skill`, `task_archive`, `task_assign_next`, `task_block`,
    `task_claim`, `task_create`, `task_delete`, `task_get`, `task_list`, `task_release`,
    `task_unarchive`, `task_unblock`, `task_update`, `job_get`, `job_list`, `job_stop`
  - shared git: `git_status`, `git_diff`, `git_history`
  - shared workspace intelligence: `workspace_symbols`, `workspace_references`, `workspace_outline`, `workspace_test_targets`
- agents:
  - scenario-pack-owned workflow roles: `coding-planner`, `reviewer`, `verifier`
  - generic first-party baseline: `plan`, `verification`, `planner`, `coordinator`, `worker`
- skills:
  - scenario-pack-owned workflow skills: `coding-loop`, `review-change`, `verify-change`, `task-discipline`, `repo-onboard`
  - generic first-party baseline: `verify`, `debug`, `stuck`, `batch`, `simplify`

default boundaries:

- workspace-oriented by default
- shell and file mutation are expected surfaces
- verification / review loops stay visible
- app 可以保留自己的 main shell agent 与 `bash` replacement
- package-owned profile guidance 通过 hook-stage context contributor 注入

### 5.2 Chat pack

reference package:

- `weavert-scenario-chat`

recommended first-party packages:

- `weavert-memory`

shared-package dependencies:

- `weavert-shared-retrieval`
- `weavert-bridge-web`

expected profile tools / agents / skills
(after recommended first-party packages are enabled):

- tools:
  - shared retrieval: `retrieve_context`, `prepare_citations`
  - shared web grounding: `grounding_web_search`, `grounding_web_fetch`
  - workflow control: `ask_user`
- agents:
  - scenario-pack-owned workflow roles: `researcher`, `support-agent`, `memory-curator`
- skills:
  - shared first-party baseline: `remember`
  - scenario-pack-owned workflow skills: `chat-summarize`, `answer-with-citations`, `clarify-request`, `capture-preferences`

default boundaries:

- read-mostly by default
- no implicit workspace writes
- no implicit shell execution
- retrieval / web grounding 继续归 shared package 所有
- workflow agents / skills 继续归 chat scenario pack 所有
- package-owned profile guidance 通过 hook-stage context contributor 注入

### 5.3 Local assistant pack

reference package:

- `weavert-scenario-local-assistant`

recommended first-party packages:

- `weavert-memory`

shared-package dependencies:

- `weavert-shared-retrieval`
- `weavert-bridge-browser`
- `weavert-bridge-local-os`
- `weavert-bridge-pim`

expected profile tools / agents / skills
(after recommended first-party packages are enabled):

- tools:
  - shared retrieval: `retrieve_context`, `prepare_citations`
  - workflow control: `ask_user`, `skill`
  - browser bridge: `browser_snapshot`, `browser_stage_navigation`, `browser_stage_interaction`
  - local OS bridge: `local_os_snapshot`, `local_os_stage_file_change`,
    `local_os_stage_process_launch`, `local_os_stage_notification`
  - PIM bridge: `pim_list_agenda`, `pim_lookup_contacts`, `pim_stage_calendar_event`,
    `pim_stage_reminder`, `pim_stage_task`
- agents:
  - `assistant-planner`
  - `assistant-action-worker`
  - `assistant-recovery`
- skills:
  - `remember`
  - `safe-action-check`
  - `daily-brief`
  - `resume-interrupted-task`
  - `research-and-act`

host-facing assumptions:

- host owns desktop or device mediation
- host decides which browser / OS / PIM bridges are actually bound
- host owns approval UX for high-risk actions
- host 如果要 materialize live bridge state，建议在 app-owned layer 自己绑定
  `weavert.local_assistant.bridge.browser` /
  `weavert.local_assistant.bridge.local_os` /
  `weavert.local_assistant.bridge.pim` 之类的 host facet

default boundaries:

- host-centric by default
- stronger permission and audit expectations than chat
- bridge-heavy composition without implicit coding surfaces
- package-owned profile guidance 通过 hook-stage context contributor 注入

staged scope boundaries:

- first step is retrieval + host-mediated bridges
- full automation ecosystems are later follow-up work
- bridge tool 只负责 stage request 或声明缺少 host bridge；
  final host mediation、final allowlist、final audit sink 都仍然是 app-owned layer

## 6. Reference activation path

这些 reference shape 不引入新 API，而是继续走现有 config surface。
默认 distribution baseline 也不会自动带入它们；reference path 仍然要求调用方显式 admission +
request 这些 external/optional packages。
同时它们现在有两条官方 inspect path：

- `weavert.services.metadata["package_manifests"]`
  - 看 projected package-surface metadata，例如 `package_candidate`、`scenario_profile`、
    `expected_tools`、`workflow_agent_ids`、`workflow_skill_ids`
- `RuntimeServices.require_capability(...)`
  - 看 scenario-pack capability payload 里镜像出来的 profile contract，例如
    `expected_tools` / `expected_agents` / `expected_skills` /
    `workflow_agent_ids` / `workflow_skill_ids` / `app_owned_wiring`

最直接的 reference activation 写法如下：

```python
from pathlib import Path

from weavert.runtime_kernel import RuntimeConfig, assemble_runtime
from weavert.scenario_runtime_packs import reference_scenario_runtime_pack_manifests

runtime = assemble_runtime(
    RuntimeConfig(
        working_directory=Path.cwd(),
        distribution="weavert-core",
        enabled_packages={
            "weavert-devtools",
            "weavert-planning",
            "weavert-builtin-workflows",
        },
        extra_package_manifests=reference_scenario_runtime_pack_manifests(),
        requested_packages={"weavert-scenario-coding"},
    )
)
```

chat 与 local assistant 只需要把：

- `enabled_packages`
- `requested_packages`

换成各自 profile 推荐值即可。

如果你只 request scenario pack，但没有同时启用它推荐的 first-party package，
那么 runtime 只会装出：

- scenario-pack capability metadata
- shared-package dependency graph
- shared-package-owned grounding tools
- scenario-pack-owned workflow agents / skills
- package-owned profile guidance context contributor
- scenario-pack-specific warning diagnostics

而不会自动 materialize 依赖 first-party package 的那部分 generic expected tools / agents / skills。
换句话说，coding pack 自己拥有的 `coding-planner` / `reviewer` / `verifier` 和
`coding-loop` / `review-change` / `verify-change` / `task-discipline` / `repo-onboard`
仍然会出现；但 `plan` / `verification` / `planner` / `coordinator` / `worker` 等 generic
first-party surfaces 仍然需要 app-owned package selection。chat pack 也是一样：
`researcher` / `support-agent` / `memory-curator` 与它们的 workflow skills 会随 scenario pack
出现，`retrieve_context` / `prepare_citations` / `grounding_web_search` / `grounding_web_fetch`
会随 shared package 依赖出现，但 `remember` 仍然依赖你显式启用 `weavert-memory`。

注意这里的 ownership split：

- first-party package selection 仍由 app config 决定
- external scenario pack admission 仍由 `extra_package_manifests` / `requested_packages` 决定
- scenario pack 只是在普通 runtime package contract 上公开一套 product-profile guidance

### 6.1 Four common user recipes

对最终接入方来说，当前最常见的不是“逐个研究所有 reference package”，而是先从下面四种入口里选一种：

如果你要的是更偏“复制就能跑”的终端用户 quickstart，直接看：

- `docs/weavert-scenario-runtime-pack-quickstart.md`

1. `weavert-scenario-coding`
2. `weavert-scenario-chat`
3. `weavert-scenario-local-assistant`
4. 只 request 某些 shared package，而不启用完整 scenario pack

这四种入口都共享同一个 baseline：

- 它们都不是默认 distribution baseline 的一部分
- 它们都必须通过 `RuntimeConfig.extra_package_manifests` admission
- 它们都必须通过 `RuntimeConfig.requested_packages` 才会真正进入 active runtime

#### 6.1.1 AI coding

适合：

- CLI coding shell
- IDE coding assistant
- repo-oriented coding workflow

推荐 package 选择：

- scenario pack
  - `weavert-scenario-coding`
- recommended first-party packages
  - `weavert-devtools`
  - `weavert-planning`
  - `weavert-builtin-workflows`

最小写法：

```python
from pathlib import Path

from weavert.runtime_kernel import RuntimeConfig, assemble_runtime
from weavert.scenario_runtime_packs import reference_scenario_runtime_pack_manifests

runtime = assemble_runtime(
    RuntimeConfig(
        working_directory=Path.cwd(),
        distribution="weavert-core",
        enabled_packages={
            "weavert-devtools",
            "weavert-planning",
            "weavert-builtin-workflows",
        },
        extra_package_manifests=reference_scenario_runtime_pack_manifests(),
        requested_packages={"weavert-scenario-coding"},
    )
)
```

启用后，用户通常会关心：

- shared coding tools
  - `git_status`, `git_diff`, `git_history`
  - `workspace_symbols`, `workspace_references`, `workspace_outline`, `workspace_test_targets`
- scenario-pack-owned workflow agents / skills
  - `coding-planner`, `reviewer`, `verifier`
  - `coding-loop`, `review-change`, `verify-change`, `task-discipline`, `repo-onboard`

#### 6.1.2 AI chat

适合：

- grounded Q&A
- support chat
- citation-aware assistant

推荐 package 选择：

- scenario pack
  - `weavert-scenario-chat`
- recommended first-party packages
  - `weavert-memory`

最小写法：

```python
from pathlib import Path

from weavert.runtime_kernel import RuntimeConfig, assemble_runtime
from weavert.scenario_runtime_packs import reference_scenario_runtime_pack_manifests

runtime = assemble_runtime(
    RuntimeConfig(
        working_directory=Path.cwd(),
        distribution="weavert-core",
        enabled_packages={"weavert-memory"},
        extra_package_manifests=reference_scenario_runtime_pack_manifests(),
        requested_packages={"weavert-scenario-chat"},
    )
)
```

启用后，用户通常会关心：

- shared grounding tools
  - `retrieve_context`, `prepare_citations`
  - `grounding_web_search`, `grounding_web_fetch`
- scenario-pack-owned workflow agents / skills
  - `researcher`, `support-agent`, `memory-curator`
  - `chat-summarize`, `answer-with-citations`, `clarify-request`, `capture-preferences`

#### 6.1.3 Local assistant

适合：

- 桌面工作助手
- device-centric assistant
- host-mediated personal workflow assistant

推荐 package 选择：

- scenario pack
  - `weavert-scenario-local-assistant`
- recommended first-party packages
  - `weavert-memory`

最小写法：

```python
from pathlib import Path

from weavert.runtime_kernel import RuntimeConfig, assemble_runtime
from weavert.scenario_runtime_packs import reference_scenario_runtime_pack_manifests

runtime = assemble_runtime(
    RuntimeConfig(
        working_directory=Path.cwd(),
        distribution="weavert-core",
        enabled_packages={"weavert-memory"},
        extra_package_manifests=reference_scenario_runtime_pack_manifests(),
        requested_packages={"weavert-scenario-local-assistant"},
    )
)
```

启用后，用户通常会关心：

- shared retrieval / bridge tools
  - `retrieve_context`, `prepare_citations`
  - `browser_snapshot`, `browser_stage_navigation`, `browser_stage_interaction`
  - `local_os_snapshot`, `local_os_stage_file_change`, `local_os_stage_process_launch`, `local_os_stage_notification`
  - `pim_list_agenda`, `pim_lookup_contacts`, `pim_stage_calendar_event`, `pim_stage_reminder`, `pim_stage_task`
- scenario-pack-owned workflow agents / skills
  - `assistant-planner`, `assistant-action-worker`, `assistant-recovery`
  - `safe-action-check`, `daily-brief`, `resume-interrupted-task`, `research-and-act`

但这里要特别注意：

- package 只提供 staged / host-mediated bridge contract
- live browser / OS / PIM authority 仍然是 app-owned host binding
- 如果不额外绑定 host facet，这些 bridge tools 只会返回 staged receipt 或 `host_bridge_required`

#### 6.1.4 Shared packages only

适合：

- 你只想给现有 app 增加一块复用 capability
- 你不想引入完整 scenario workflow 角色
- 你已经有自己的主 agent / shell / host UX

常见组合：

- coding augmentation
  - `weavert-shared-git`
  - `weavert-shared-workspace-intelligence`
- grounded chat augmentation
  - `weavert-shared-retrieval`
  - `weavert-bridge-web`
- local assistant bridge augmentation
  - `weavert-bridge-browser`
  - `weavert-bridge-local-os`
  - `weavert-bridge-pim`

最小写法：

```python
from pathlib import Path

from weavert.runtime_kernel import RuntimeConfig, assemble_runtime
from weavert.scenario_runtime_packs import reference_scenario_runtime_pack_manifests

runtime = assemble_runtime(
    RuntimeConfig(
        working_directory=Path.cwd(),
        distribution="weavert-core",
        extra_package_manifests=reference_scenario_runtime_pack_manifests(),
        requested_packages={
            "weavert-shared-retrieval",
            "weavert-bridge-web",
        },
    )
)
```

这种模式下：

- runtime 会 materialize 你 request 的 shared tool surface
- 但不会额外带入 coding/chat/local assistant 的高层 workflow agents / skills
- 更适合已有产品在 app-owned shell 上做增量 capability attach

## 7. App-owned wiring examples

下面三种 wiring example 都故意把 provider、store、host、permission 放在 scenario pack 外面。
如果应用还想记录 deployable shell 的组装约定，推荐把 `app_kind`、scenario package、
host expectation、final permission notes 保留在 app-owned config / docs / code 里，而不是把
它们升级成第三种 manifest-owned package family。

### 7.1 Coding app wiring

- scenario pack
  - `weavert-scenario-coding`
- shared packages
  - `weavert-shared-git`
  - `weavert-shared-workspace-intelligence`
- app-owned provider choice
  - 例如 `openai_default` 或其他 route
- app-owned store choice
  - transcript / child-run store 可用 file-backed durable store
- app-owned host binding
  - CLI、IDE shell、terminal-oriented host
- app-owned shell layer
  - main coding shell agent、host UX、`bash` replacement 等仍然留在 app 里
- app-owned permission composition
  - coding-grade read/write posture，外加 deployment-specific allowlist / approval policy

### 7.2 Chat app wiring

- scenario pack
  - `weavert-scenario-chat`
- app-owned provider choice
  - 由产品自己选择 route / gateway
- app-owned store choice
  - in-memory 或 hosted transcript store 都可
- app-owned host binding
  - web UI、mobile shell、support console
- app-owned permission composition
  - read-only 或 approval-first baseline；任何 write-capable bridge 都由应用单独决定是否开放

### 7.3 Local assistant app wiring

- scenario pack
  - `weavert-scenario-local-assistant`
- app-owned provider choice
  - 由应用决定本地/远端 route 与 fallback
- app-owned store choice
  - durable transcript、job、memory store 更常见
- app-owned host binding
  - desktop shell、device shell、system tray、OS-integrated host
- app-owned permission composition
  - browser / OS / PIM actions 使用 staged approval + audit sink；最终 allowlist 仍归应用
- app-owned bridge execution
  - scenario pack / shared package 可以给出 staged request，但真正执行 request 的 browser / OS / PIM adapter 仍归应用装配

如果要把这些 boundary 落到代码里，推荐把 scenario pack 当成下面这个组合里的其中一层，而不是整个产品：

```text
selected first-party packages
+ requested external shared/scenario packages
+ model routes
+ stores
+ bind_host(host)
+ final permission policies
= deployable app shape
```

## 8. Validation coverage in this repository

当前 reference path 的可执行验证在 `tests/test_scenario_runtime_packs.py`，覆盖了三件事：

1. coding / chat / local-assistant reference shape 都能通过现有 runtime package contract 装配
2. chat 与 local assistant 不会因为 reference shape 而隐式继承 coding-oriented workspace / shell / planning / workflow surface，例如 `read` / `glob` / `grep` / `edit` / `write` / `bash`、`plan` / `verification` / `planner` / `coordinator` / `worker`、以及 `verify` / `debug` / `stuck` / `batch` / `simplify`
3. shared retrieval / bridge package 会按 scenario-pack dependency 被组合进 active graph

这条验证路径的目的，是把 scenario pack 证明成 ordinary runtime package composition，而不是文档里的抽象说法。

## 9. Follow-up evaluation

### 9.1 Demos vs templates vs first-party packaged profiles

当前建议是：

- 先把 reference scenario pack 保持为 docs + reference manifests + tests
- 需要 runnable story 时，优先补轻量 demo
- 暂时不要立刻把它们升级成新的 first-party packaged profile taxonomy

原因：

- 现在最缺的是 ownership guidance 与 validation story
- 不是新的 distribution tier
- 过早产品化会把 provider/store/host/policy authority 错误地吸进 scenario pack

后续如果下面几件事稳定下来，再讨论是否升级：

- adopters 对 reference shapes 的复用路径足够清晰
- shared bridge package boundary 稳定
- app-owned wiring 和 scenario-pack boundary 不再反复调整

### 9.2 Scenario-pack scaffolding

starter-generation 或 scaffolding 适合后续 change，再做更稳妥。

当前不建议先把它做成 starter generator，原因是：

- 参考形态本身还在验证 ownership split
- local assistant 的 host / permission / audit surface 仍有 staged boundary
- 如果太早固化脚手架，容易把临时 reference shape 误包装成长期 contract

因此当前结论是：

- 先稳定 architecture
- 再稳定 validation story
- 最后再考虑 starter-generation / scaffolding change
