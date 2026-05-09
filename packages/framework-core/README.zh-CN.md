# Core Package

这个页面索引 `packages/framework-core/`，这里拥有 runtime kernel 和共享框架原语。

## 这个 package 拥有什么

- 公开的 `weavert` runtime package
- runtime kernel 与稳定 assembly surfaces
- 仍属于 core import root 的共享框架原语

## 规范名称

- 安装名：`weavert`
- import root：`weavert`

## 邻接家族

- `packages/framework-packs/` 拥有从 core package 中抽离出来的 first-party add-on packages。
- `packages/product-kits/` 拥有 scenario packs 与共享 product-kit packages。
- `packages/toolchain/` 拥有围绕 runtime 使用的 starter 与 testing tooling。

## 另见

- `../README.zh-CN.md`
- `../framework-packs/README.zh-CN.md`
- `../product-kits/README.zh-CN.md`
- `../../docs/zh-CN/concepts/runtime-model.md`
- `../../docs/zh-CN/architecture/overview.md`
