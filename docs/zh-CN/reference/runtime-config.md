# RuntimeConfig 参考

`RuntimeConfig` 是普通框架使用者最主要的 assembly surface。

## 适合谁？

- 已理解整体工作流、现在需要稳定查询页的读者。

## 前置条件

- 先读对应的 guide 或 concept 页面
- 把这页当成 reference sheet，而不是第一站教程

## 最常用 presets

- `RuntimeConfig.for_ordinary_workflow(project_root)`
  - 普通项目本地 workflow baseline
- `RuntimeConfig.for_headless_live(project_root)`
  - 适合 preflight 的 live route baseline
- `RuntimeConfig.for_host_bound(project_root)`
  - 面向 CLI、SDK 或 UI 集成的 host-oriented baseline

## `RuntimeConfig` 通常承载的决定

最重要的配置槽位通常分为这些组：

- distribution 与 package posture
  - `distribution`
  - `enabled_packages` / `disabled_packages`
  - `extra_package_manifests`
  - `requested_packages`
- working roots 与 discovery
  - `working_directory`
  - user 和 project `.weavert/` 等 discovery sources
- model layer
  - `model_client`
  - model providers 与 routes
- control-plane 与 persistence layer
  - host bindings
  - transcript 与 child-run stores
  - memory configuration

## 良好的默认姿态

只要可能，就先从 preset 开始。
只添加你确实需要的额外控制。

## 什么时候该超出 preset

当你需要下面这些能力时，再手动构造 `RuntimeConfig(...)`：

- 非默认 package selection
- 自定义 transcript 或 child-run stores
- 自定义 model route wiring
- 显式 host-oriented integration

如果你需要 host-oriented baseline，但又不想从零手写，先从 `RuntimeConfig.for_host_bound(...)` 开始，然后只覆盖 host 需要的部分。

对于 memory 行为，请区分两种情况：

- 需要声明式调优时，用 `RuntimeConfig.memory_config`
- 如果你真的需要替换 memory backend，目前这比 `RuntimeConfig` 更深，因为还没有直接的 `RuntimeConfig.memory_provider` 槽位

## 下一步

- 如果你仍想沿着 preset-first 采纳路径继续，回到 `../guides/build-your-first-project.md`
- 如果下一步改动是 live route 或 provider 配置，进入 `../guides/integrate-openai.md`
- 如果你正在调整 package admission 或 activation，读 `../architecture/package-system.md`

## 另见

- `../concepts/runtime-model.md`
- `../guides/build-your-first-project.md`
- `../guides/integrate-openai.md`
- `../architecture/package-system.md`
- `../getting-started/quickstart.md`
- `../deep-dives/weavert-integration-guide.md`
