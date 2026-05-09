# Package 系统

WeaveRT 采用显式 package composition，让能力保持可检查。

## 适合谁？

- 正在评估 runtime 在底层如何被组装、执行和持久化的读者。

## 前置条件

- 先读 `../concepts/runtime-model.md`
- 在把这层当作更深的架构层之前，先用 concepts 页面补齐词汇

## Distribution 层

- `weavert-core`
  - runtime kernel 与稳定契约
- `weavert-default`
  - core + 常见 first-party capability packages
- `weavert-full`
  - default + 更完整的 workflows、mechanisms 与 integrations

Distribution 负责选择粗粒度基线。
但它并不能替代显式的 package 推理。

## Package 角色

当前 first-party 角色包括：

- capability packages
  - `weavert-memory`、`weavert-team`
- mechanism packages
  - `weavert-compaction`、`weavert-isolation`
- integration packages
  - `weavert-openai`、`weavert-hosts-reference`、`weavert-stores-file`
- workflow packages
  - `weavert-planning`、`weavert-devtools`、`weavert-builtin-workflows`

## Package protocol attachment

真正的 runtime package 不只是“某个文件夹里有些文件”。
只有当它通过 manifest-backed protocol surface 参与运行时，package 边界才有意义，例如：

- `RuntimePackageManifest`
- 有依赖顺序的 resolution
- `PackageContribution`
- capability registry lookup
- lifecycle participation

这就是为什么 package composition 应属于 runtime assembly，而不是某种临时目录约定。

## Admitted packages 与 active packages

外部 packages 通常分两步进入系统：

- admission
  - manifests 通过 `extra_package_manifests` 成为候选
- activation
  - package 通过 `requested_packages` 和兼容性 resolution 进入最终解析图

这个区分很重要，因为一个 package 可以作为候选可见，但此时还没有真正贡献 runtime surfaces。

## 为什么这在操作上重要

显式 package activation 帮你回答：

- 哪个 surface 当前存在
- 它属于哪个 package
- 一个 package 只是被 admitted，还是已经 active
- 某个 scenario pack 与 host ownership 的关系是什么

## Scenario packs 仍然属于 package composition

Scenario packs 不会替代 distributions，也不会替代 `.weavert/`。
它们仍然是叠加在 runtime package system 之上的普通 package-selection surface。

## 下一步

- 如果你正在激活某个 product profile 或 shared package 集合，进入 `../guides/use-scenario-packs.md`
- 如果你想看驱动 package posture 的具体 assembly 字段，打开 `../reference/runtime-config.md`
- 如果你在把旧的 package-boundary 假设映射到新布局，读 `../maintainers/migration-notes.md`

## 另见

- `../concepts/packages-and-scenario-packs.md`
- `../deep-dives/weavert-scenario-runtime-pack-architecture.md`
- `../maintainers/runtime-boundary-migration-ledger.md`
