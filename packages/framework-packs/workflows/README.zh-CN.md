# Framework-Pack Workflows

由 workflow 拥有的 first-party add-ons 现在位于这个工作区家族下。

## 这个角色家族拥有什么

- 不属于 scenario packs 的 first-party workflow packages
- 能跨多种产品形态共享的可复用 planning、devtools 或 built-in workflow surfaces

## 具体 packages

- `planning/`：`weavert-planning`，import root 为 `weavert_planning`
- `devtools/`：`weavert-devtools`，import root 为 `weavert_devtools`
- `builtin-workflows/`：`weavert-builtin-workflows`，import root 为 `weavert_builtin_workflows`

## 所有权规则

- 把可复用的 first-party workflow packages 放在这里。
- 如果这个 package 是带产品画像默认值的 scenario pack，请改用 `packages/product-kits/`。

## 另见

- `../README.zh-CN.md`
- `planning/README.zh-CN.md`
- `devtools/README.zh-CN.md`
- `builtin-workflows/README.zh-CN.md`
- `../../../examples/README.zh-CN.md`
