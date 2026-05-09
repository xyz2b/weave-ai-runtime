# Framework-Pack Capabilities

由 capability 拥有的 first-party add-ons 现在位于这个工作区家族下。

## 这个角色家族拥有什么

- 可复用的 first-party capability packages
- 能为 runtime 增加可见能力、但不属于 product kits 或 toolchain utilities 的 package surfaces

## 具体 packages

- `memory/`：`weavert-memory`，import root 为 `weavert_memory`
- `team/`：`weavert-team`，import root 为 `weavert_team`

## 所有权规则

- 当一个可复用 capability surface 属于 first-party add-on family 时，把它放在这里。
- 如果它实际上是 scenario pack 或共享 product-kit package，请使用 `packages/product-kits/`。

## 另见

- `../README.zh-CN.md`
- `memory/README.zh-CN.md`
- `team/README.zh-CN.md`
- `../../../docs/zh-CN/README.md`
