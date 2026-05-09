# Framework-Pack Mechanisms

由 mechanism 拥有的 first-party add-ons 现在位于这个工作区家族下。

## 这个角色家族拥有什么

- first-party runtime mechanisms，例如 compaction 或 isolation
- 用于塑造 runtime 行为、但不属于 capability packs 或 product kits 的 packages

## 具体 packages

- `compaction/`：`weavert-compaction`，import root 为 `weavert_compaction`
- `isolation/`：`weavert-isolation`，import root 为 `weavert_isolation`

## 所有权规则

- 当可复用 runtime mechanisms 属于 first-party add-on family 时，把它们放在这里。
- app-specific policy 与 UX 不应进入这个 family。

## 另见

- `../README.zh-CN.md`
- `compaction/README.zh-CN.md`
- `isolation/README.zh-CN.md`
- `../../../docs/zh-CN/architecture/request-lifecycle.md`
