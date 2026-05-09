# Toolchain Scripts

这个 package root 拥有仓库支持脚本。它们有意保持为开发者侧 utilities，而不是 runtime-selected packages。

## 这个 package 拥有什么

- 供维护者与验证工作流使用的仓库支持脚本
- 不应表现为 runtime-selected packages 的开发者侧 utilities

## 规范名称

- 安装名：`weavert-toolchain-scripts`
- 公开 import root：无；直接使用脚本路径

## 规范脚本路径

- `packages/toolchain/scripts/check_workspace_layout.py`
- `packages/toolchain/scripts/openai_responses_live_smoke.py`

## 另见

- `../README.zh-CN.md`
- `../../../docs/zh-CN/maintainers/repository-layout.md`
- `../../../docs/zh-CN/guides/integrate-openai.md`
