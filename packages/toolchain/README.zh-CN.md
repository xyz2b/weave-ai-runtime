# Toolchain

这个 family root 索引面向开发者的具体 toolchain packages，同时覆盖公开 tooling 与仓库拥有的维护者 utilities。

## 这个 family 拥有什么

- 不进入 runtime package 选择的开发者侧工具
- 采纳路径的 starter generator、验证路径的 testing kit，以及仓库支持脚本

## 公开发布边界

- `starter/` 与 `testing/` 是公开 PyPI projects。
- `scripts/` 保留 package-local metadata，用于仓库 checkout 或本地 maintainer install，但不进入公开 PyPI 发布列车。
- 这些 package 都不是 runtime activation targets。

## 具体 packages

- `starter/` -> 规范 import root `weavert_starter`，拥有采纳路径 starter generator
- `testing/` -> 规范 import root `weavert_testing`，拥有验证路径 testing kit
- `scripts/` -> 仓库拥有的维护者脚本 root，安装名 `weavert-toolchain-scripts`，不属于公开 PyPI train

## 所有权规则

- 这些 packages 保持在 runtime package selection 之外。
- 应通过开发工作流、imports 或 CLI entrypoints 访问它们，而不是通过 runtime package activation。

## 另见

- `../README.zh-CN.md`
- `starter/README.zh-CN.md`
- `testing/README.zh-CN.md`
- `../../docs/zh-CN/getting-started/starter-scaffolds.md`
- `../../examples/README.zh-CN.md`
