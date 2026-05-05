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
| scenario pack | product-profile defaults, shared-package composition, expected agent/skill posture | final host binding, mandatory provider selection, final permission composition |
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
`src/weavert/scenario_runtime_packs.py`：

- `weavert-shared-retrieval`
  - retrieval-oriented shared package example
  - 适合 chat / local assistant 复用
- `weavert-bridge-web`
  - web / HTTP capability surface
- `weavert-bridge-browser`
  - browser bridge surface
- `weavert-bridge-local-os`
  - local OS bridge surface
- `weavert-bridge-pim`
  - PIM bridge surface

这些 shared package 现在都通过 ordinary capability-only package pattern 表达，目的不是把它们产品化，而是明确：

- retrieval 不应该被塞进每一个 scenario pack 私有实现里
- browser / local OS / PIM bridge 不应该在每个 assistant profile 里重复实现
- scenario pack 应该组合它们，而不是吸收它们的所有权

## 5. Reference scenario pack shapes

### 5.1 Coding pack

reference package:

- `weavert-scenario-coding`

recommended first-party packages:

- `weavert-devtools`
- `weavert-planning`
- `weavert-builtin-workflows`

shared-package dependencies:

- none in the first reference path

expected profile agents / skills
(after recommended first-party packages are enabled):

- agents: `plan`, `verification`, `planner`, `coordinator`, `worker`
- skills: `verify`, `debug`, `stuck`, `batch`, `simplify`

default boundaries:

- workspace-oriented by default
- shell and file mutation are expected surfaces
- verification / review loops stay visible
- package-owned profile guidance 通过 hook-stage context contributor 注入

### 5.2 Chat pack

reference package:

- `weavert-scenario-chat`

recommended first-party packages:

- `weavert-memory`

shared-package dependencies:

- `weavert-shared-retrieval`
- `weavert-bridge-web`

expected profile agents / skills
(after recommended first-party packages are enabled):

- agents: none by default
- skills: `remember`

default boundaries:

- read-mostly by default
- no implicit workspace writes
- no implicit shell execution
- grounding / retrieval remain shared-package concerns
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

expected profile agents / skills
(after recommended first-party packages are enabled):

- agents: none by default
- skills: `remember`

host-facing assumptions:

- host owns desktop or device mediation
- host decides which browser / OS / PIM bridges are actually bound
- host owns approval UX for high-risk actions

default boundaries:

- host-centric by default
- stronger permission and audit expectations than chat
- bridge-heavy composition without implicit coding surfaces
- package-owned profile guidance 通过 hook-stage context contributor 注入

staged scope boundaries:

- first step is retrieval + host-mediated bridges
- full automation ecosystems are later follow-up work

## 6. Reference activation path

这些 reference shape 不引入新 API，而是继续走现有 config surface。

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
- package-owned profile guidance context contributor
- scenario-pack-specific warning diagnostics

而不会自动 materialize shape 里列出的 expected agents / skills。

注意这里的 ownership split：

- first-party package selection 仍由 app config 决定
- external scenario pack admission 仍由 `extra_package_manifests` / `requested_packages` 决定
- scenario pack 只是在普通 runtime package contract 上公开一套 product-profile guidance

## 7. App-owned wiring examples

下面三种 wiring example 都故意把 provider、store、host、permission 放在 scenario pack 外面。

### 7.1 Coding app wiring

- scenario pack
  - `weavert-scenario-coding`
- app-owned provider choice
  - 例如 `openai_default` 或其他 route
- app-owned store choice
  - transcript / child-run store 可用 file-backed durable store
- app-owned host binding
  - CLI、IDE shell、terminal-oriented host
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
