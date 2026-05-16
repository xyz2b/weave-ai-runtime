# 公开包目录

这页描述 WeaveRT 的公开 first-party package surface。
当你需要一个统一页面来回答下面三个问题时，就读这页：

- 每个已发布包是做什么的
- 这些包通常该怎么用
- install name、import root 与 runtime activation name 是什么关系

## 适合谁？

- 从 PyPI 或 TestPyPI 选择公开包的使用者
- 需要一份对外公开包清单的维护者
- 正在判断自己需要 baseline bundle、framework pack、scenario kit，还是只需要一个 shared bridge kit 的采纳者

## 用“分层”方式理解这个目录

公开包面分成四层：

1. baseline runtime 与 toolchain packages
2. 直接扩展 runtime 的 framework packs
3. 暴露 lower-layer bridges 的 shared product-kit packages
4. 发布 higher-layer product-profile defaults 的 scenario kits

Toolchain packages 永远不是 runtime activation targets。
Scenario kits 与 shared kits 需要 package manifests 加 `requested_packages`；它们的公开 install name 不等于 runtime activation name。

## 快速安装入口

公开安装路径默认优先用下面三种：

- starter-first 采纳路径：

```bash
python -m pip install weavert-starter weavert-testing
```

- 不使用 scaffold 的完整 runtime baseline：

```bash
python -m pip install weavert-full
```

- 从最小 kernel 开始做窄定制：

```bash
python -m pip install weavert
```

## Runtime baselines 与 toolchain

| Install name | Import root | Runtime activation | 提供什么 | 适用场景 |
| --- | --- | --- | --- | --- |
| `weavert` | `weavert` | none | Core runtime kernel、assembly APIs、definition discovery 与 extension seams | 你想从最小自定义起点开始，并自己决定 add-ons |
| `weavert-full` | none | none | 与 `RuntimeConfig.for_ordinary_workflow(...)` 对齐的可安装完整 first-party baseline | 你想要标准 first-party runtime surface，但不需要 starter CLI |
| `weavert-starter` | `weavert_starter` | none | 官方 starter scaffolds 与 `weavert-starter` CLI | 你想走最快的项目启动路径 |
| `weavert-testing` | `weavert_testing` | none | 确定性 testing harness、scripted model support、fixtures 与 assertions | 你想为 WeaveRT app 做离线验证或回归测试 |

## Framework packs

这些是直接的 first-party runtime add-ons。
`weavert-full` 已经包含下表里的常见 baseline set。
只有当你要缩窄或重组 surface，而不是直接采用 full baseline 时，才需要单独安装它们。

| Install name | Import root | 角色 | 增加什么 | 典型用途 |
| --- | --- | --- | --- | --- |
| `weavert-memory` | `weavert_memory` | Capability | 分层 memory runtime support 与 memory-specific services | 给自定义 runtime 增加持久或会话记忆行为 |
| `weavert-team` | `weavert_team` | Capability | Team control 与 teammate orchestration surfaces | 增加 multi-agent 或 teammate-style coordination |
| `weavert-compaction` | `weavert_compaction` | Mechanism | Compaction strategies 与 manager support | 在较长工作流里降低上下文压力 |
| `weavert-isolation` | `weavert_isolation` | Mechanism | Isolation adapters 与 scoped execution boundaries | 为工具或宿主执行建立显式隔离边界 |
| `weavert-openai` | `weavert_openai` | Integration | First-party OpenAI provider binding 与 route surfaces | 使用 live OpenAI model routes |
| `weavert-hosts-reference` | `weavert_hosts_reference` | Integration | Reference CLI 与 SDK host implementations | 用可复用 host 示例起步，而不是从零构建 host shell |
| `weavert-stores-file` | `weavert_stores_file` | Integration | File-backed transcript 与 runtime stores | 使用本地持久状态、transcript capture 或 file-backed testing |
| `weavert-builtin-workflows` | `weavert_builtin_workflows` | Workflow | 可复用 first-party workflow skills | 复用位于 scenario-pack 之下的共享 workflow behavior |
| `weavert-planning` | `weavert_planning` | Workflow | Planning agents 与 coordinator-style planning support | 增加 planner、coordinator 或 task-list 风格的工作流表面 |
| `weavert-devtools` | `weavert_devtools` | Workflow | Workspace 与 coding built-ins | 增加面向开发者的 workflow helpers 与 coding surfaces |

## Shared product-kit packages

这些是 lower-layer building blocks。
当你只想拿一个可复用 bridge 或 shared capability，而不想直接采用完整 scenario profile 时，用它们。

| Install name | Import root | Runtime activation | 增加什么 | 典型用途 |
| --- | --- | --- | --- | --- |
| `weavert-kit-common-retrieval` | `weavert_kit_common_retrieval` | `weavert-shared-retrieval` | Shared retrieval surfaces | 在 chat 或 assistant 产品间复用 retrieval support |
| `weavert-kit-common-web` | `weavert_kit_common_web` | `weavert-bridge-web` | 带 compact `web_research`、provider metadata 和 freshness outcome 的只读 web grounding surfaces | 增加 web grounding，但不采用完整 chat profile |
| `weavert-kit-common-git` | `weavert_kit_common_git` | `weavert-shared-git` | Shared git inspection surfaces | 给自定义 coding workflow 增加 repository inspection |
| `weavert-kit-common-workspace-intelligence` | `weavert_kit_common_workspace_intelligence` | `weavert-shared-workspace-intelligence` | Shared workspace-intelligence surfaces | 增加 workspace-aware coding support |
| `weavert-kit-common-browser` | `weavert_kit_common_browser` | `weavert-bridge-browser` | Shared browser bridge surfaces | 给 host-centric assistant 增加 browser-side interaction |
| `weavert-kit-common-local-os` | `weavert_kit_common_local_os` | `weavert-bridge-local-os` | Shared local-OS bridge surfaces | 增加本地机器 bridge 行为，但不采用完整 scenario pack |
| `weavert-kit-common-pim` | `weavert_kit_common_pim` | `weavert-bridge-pim` | Shared PIM bridge surfaces | 增加 calendar、notes 或个人信息管理类 bridge |

## 常见易混 shared kits

- `weavert-kit-common-retrieval` 负责对你已经拿到的 grounding 项做排序、摘录和 citation 准备，比如 notes、memory 或 fetched passages。它自己不做公网搜索，也不驱动浏览器。
- `weavert-kit-common-web` 负责只读的公网 web 搜索与受限远程抓取，用于 grounding。它不提供浏览器导航、点击，或宿主侧浏览器控制。
- `weavert-kit-common-browser` 是一个经由 host mediation 的 browser bridge，用于浏览器状态、导航和交互。它不是 web 搜索适配器，也不意味着 runtime 自主拥有浏览器。
- `weavert-kit-common-local-os` 桥接的是 files、clipboard、notifications、processes 这类通用本地机器表面。它是更宽的设备桥接，不是结构化个人信息工具。
- `weavert-kit-common-pim` 桥接的是 calendar events、contacts、reminders、tasks 这类结构化个人信息表面。需要 PIM objects 时选它，不要把它和通用 local-OS access 混在一起。

## Scenario kits

这些是 higher-layer product-profile entrypoints。
它们仍然不拥有你的最终 host、provider routes 或 permission posture。
它们发布的是一套需要由 app 显式组合的 package-selection baseline。

| Install name | Import root | Runtime activation | 增加什么 | 组合了什么 |
| --- | --- | --- | --- | --- |
| `weavert-kit-chat` | `weavert_kit_chat` | `weavert-scenario-chat` | Chat-oriented product-profile defaults | retrieval + web |
| `weavert-kit-coding` | `weavert_kit_coding` | `weavert-scenario-coding` | Coding-oriented product-profile defaults | git + workspace intelligence |
| `weavert-kit-local-assistant` | `weavert_kit_local_assistant` | `weavert-scenario-local-assistant` | Host-centric local-assistant profile defaults | retrieval + browser + local-OS + PIM |

## 如何使用 scenario kits

只安装 scenario kit 还不够。
你仍然需要 admit 它的 manifests，并请求它的 runtime activation name。

示例：

```python
from pathlib import Path

from weavert import RuntimeConfig, assemble_runtime
from weavert_kit_coding import coding_scenario_runtime_pack_manifests

config = RuntimeConfig.for_ordinary_workflow(Path.cwd())
config.extra_package_manifests = coding_scenario_runtime_pack_manifests()
config.requested_packages.add("weavert-scenario-coding")
runtime = assemble_runtime(config)
```

## 如何使用 shared product-kit packages

Shared kits 也是同样的模式，只是改用 lower-layer activation names。

示例：

```python
from pathlib import Path

from weavert import RuntimeConfig, assemble_runtime
from weavert_kit_common_git import reference_shared_package_manifests

config = RuntimeConfig.for_ordinary_workflow(Path.cwd())
config.extra_package_manifests = reference_shared_package_manifests()
config.requested_packages.add("weavert-shared-git")
runtime = assemble_runtime(config)
```

其他 shared kits 也保持这个模式，只替换下面三项：

- import root
- manifest helper
- 上表中的 runtime activation name

## 接下来读什么

- 按场景选包组合：`../guides/choose-package-combinations.md`
- scenario-pack 激活细节：`../guides/use-scenario-packs.md`
- runtime package-selection 模型：`../architecture/package-system.md`
- 默认 getting started 安装路径：`../getting-started/installation.md`
- source checkout 安装路径：`../getting-started/install-from-source.md`
