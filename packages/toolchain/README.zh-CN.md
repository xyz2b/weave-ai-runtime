# Toolchain

这个 family root 索引面向开发者的具体 toolchain packages。

## 这个 family 拥有什么

- 不进入 runtime package 选择的开发者侧工具
- 采纳路径的 starter generator、验证路径的 testing kit，以及仓库支持脚本

## 具体 packages

- `starter/` -> 规范 import root `weavert_starter`，拥有采纳路径 starter generator
- `testing/` -> 规范 import root `weavert_testing`，拥有验证路径 testing kit
- `scripts/` -> 仓库支持脚本

## 所有权规则

- 这些 packages 保持在 runtime package selection 之外。
- 应通过开发工作流、imports 或 CLI entrypoints 访问它们，而不是通过 runtime package activation。

## 另见

- `../README.zh-CN.md`
- `starter/README.zh-CN.md`
- `testing/README.zh-CN.md`
- `../../docs/zh-CN/getting-started/starter-scaffolds.md`
- `../../examples/README.zh-CN.md`
