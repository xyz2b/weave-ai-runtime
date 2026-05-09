# Framework Packs

这个 family root 索引扩展 runtime、但不属于 `weavert` core package 的 first-party add-on packages。
Scenario packs 不在这里，它们位于 `packages/product-kits/`。

## 这个 family 拥有什么

- 位于 core `weavert` import root 之外的 first-party add-on packages
- 以 capability、mechanism、integration 和 workflow 为角色的 package families

## 角色家族

- `capabilities/`
- `mechanisms/`
- `integrations/`
- `workflows/`

## 所有权规则

- 不要在这里添加 family-level `pyproject.toml`。
- 每个具体 pack 都在自己的角色家族下拥有 package-local metadata。
- 如果这个 package 实际上是 scenario pack 或共享 product-kit package，请使用 `packages/product-kits/`，而不是这个 family。

## 另见

- `capabilities/README.zh-CN.md`
- `integrations/README.zh-CN.md`
- `mechanisms/README.zh-CN.md`
- `workflows/README.zh-CN.md`
- `../../docs/zh-CN/framework-packs/README.md`
