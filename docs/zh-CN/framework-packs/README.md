# Framework Packs

这页索引位于 `packages/framework-packs/` 下的 first-party add-on package families。
当你想先获得 runtime add-ons 的打包地图，再去读某个具体 package README 时，使用这页。

## 这页的作用

- 解释工作区拆分后 first-party add-on packages 在哪里
- 把 framework-pack families 与 core `weavert` package、scenario packs 分开
- 提供一个关于 capability、mechanism、integration 与 workflow package families 的稳定索引

## 这里应包含什么

- 在 core `weavert` import root 之外扩展 runtime 的 first-party add-on packages
- 由 framework 拥有、适合复用，但不应建模为 scenario packs 或 app-owned host code 的 packages

Scenario packs 不在这里。
它们位于 `../../../packages/product-kits/`。

## 角色族

- `capabilities/`：`weavert-memory`、`weavert-team`
- `mechanisms/`：`weavert-compaction`、`weavert-isolation`
- `integrations/`：`weavert-openai`、`weavert-hosts-reference`、`weavert-stores-file`
- `workflows/`：`weavert-planning`、`weavert-devtools`、`weavert-builtin-workflows`

## 规范工作区根目录

- `packages/framework-packs/capabilities/`
- `packages/framework-packs/mechanisms/`
- `packages/framework-packs/integrations/`
- `packages/framework-packs/workflows/`

## 规范 import roots

- `weavert_memory`
- `weavert_team`
- `weavert_compaction`
- `weavert_isolation`
- `weavert_openai`
- `weavert_hosts_reference`
- `weavert_stores_file`
- `weavert_planning`
- `weavert_devtools`
- `weavert_builtin_workflows`

## 接下来读什么

- 想看 package-family 工作区索引：[`../../../packages/framework-packs/README.zh-CN.md`](../../../packages/framework-packs/README.zh-CN.md)
- 想看 scenario-pack 一侧的模型：[`../../../packages/product-kits/README.zh-CN.md`](../../../packages/product-kits/README.zh-CN.md)
- 想看 packages 与 scenario packs 的概念模型：[`../concepts/packages-and-scenario-packs.md`](../concepts/packages-and-scenario-packs.md)
- 想看 runtime 的 package-resolution 视角：[`../architecture/package-system.md`](../architecture/package-system.md)
