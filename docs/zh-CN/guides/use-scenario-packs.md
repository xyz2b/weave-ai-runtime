# 使用 Scenario Packs

## 适合谁？

想获得 coding、chat 或 local assistant 这类产品画像级 baseline，同时又不放弃 host 所有权的用户。

## 前置条件

- 一个可运行的 runtime baseline
- 已安装相应 product-kit package
- 已经明确你想组合哪种 profile

## 先记住的边界

Scenario pack 是一种普通 package-selection surface，不是新的 runtime mode，也不是最终 host owner。
它可以推荐 posture，并发布 workflow surfaces，但应用仍拥有：

- provider routes
- stores
- 最终 permission composition
- host UX 与 approvals

## 激活路径

规范模式是：

1. 选择 distribution
2. 通过 `extra_package_manifests` admit manifests
3. 通过 `requested_packages` 按名称请求 package
4. 检查已组装 runtime posture

最小 coding 示例：

```python
from pathlib import Path

from weavert import RuntimeConfig, assemble_runtime
from weavert_kit_coding import coding_scenario_runtime_pack_manifests

config = RuntimeConfig.for_ordinary_workflow(Path.cwd())
config.extra_package_manifests = coding_scenario_runtime_pack_manifests()
config.requested_packages.add("weavert-scenario-coding")
runtime = assemble_runtime(config)
```

## 常见 profile 配方

### Coding

适合你想要面向工作区的工具、planner/reviewer 角色，以及共享 git 或 workspace-intelligence 表面时。

导入路径：

```python
from weavert_kit_coding import coding_scenario_runtime_pack_manifests
```

### Chat

适合你想要 retrieval、citations 和 response-quality workflows 时。

导入路径：

```python
from weavert_kit_chat import chat_scenario_runtime_pack_manifests
```

### Local assistant

适合你想要更强的 host-centric posture，通常还会配合 browser、local-OS 或 PIM bridges 时。

导入路径：

```python
from weavert_kit_local_assistant import local_assistant_scenario_runtime_pack_manifests
```

### 只使用 shared packages

当你只想要可复用能力桥接，而不想采用完整 scenario workflow profile 时，走这条路径。

## 激活后应检查什么

Assembly 完成后，请检查：

- package 是否真的 active，而不只是 admitted
- 出现了哪些 workflow agents 或 skills
- 拉入了哪些 shared package dependencies
- package-specific diagnostics 是否提示缺少推荐 first-party packages

## 预期结果

Scenario pack 贡献 workflow surfaces 与 guidance，而最终 host、provider 和 permission 决策仍由应用拥有。

## 下一步

如果你想看一个建立在 coding scenario pack 之上的更丰富 host-bound 样例，进入 `../../../examples/apps/code_assistant/README.zh-CN.md`。

## 另见

- `../concepts/packages-and-scenario-packs.md`
- `../architecture/package-system.md`
- `../deep-dives/weavert-scenario-runtime-pack-quickstart.md`
- `../deep-dives/weavert-scenario-runtime-pack-architecture.md`
