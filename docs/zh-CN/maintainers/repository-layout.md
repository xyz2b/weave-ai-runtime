# 仓库布局

这个页面面向维护仓库本身的维护者与贡献者。

## 适合谁？

- 正在维护这个仓库、而不是第一次采纳框架的维护者与贡献者。

## 前置条件

- 先读 `../README.md`，确保公开文档路径不被打断
- 在修改仓库时，使用 `../../../examples/README.zh-CN.md` 作为可运行验证路径

## 顶层目录

- `docs/` -> 公开文档、deep dives 与 maintainer notes
- `examples/` -> 可运行验证路径与高级 integration samples
- `packages/` -> 可发布 package 工作区
- `tests/` -> 仓库级验证
- `openspec/` -> 变更提案、specs 与归档设计工作
- `upstreams/` -> 上游导入源码树与来源说明

## Package families

- `packages/framework-core/` -> core `weavert` runtime package
- `packages/framework-packs/` -> first-party add-on capability、mechanism、integration 与 workflow packages
- `packages/product-kits/` -> scenario 与 common-kit packages
- `packages/toolchain/` -> starter、testing 与仓库工具

当前 framework-pack 角色地图见 `../framework-packs/README.md`。

## 规范根目录

- `packages/framework-core/` -> 具体 runtime package metadata 与当前 `weavert` 实现代码
- `packages/framework-packs/` -> concrete first-party add-on packs 的 family root
- `packages/product-kits/` -> concrete product-kit 与 common-kit packages 的 family root
- `packages/toolchain/` -> concrete developer tooling packages 的 family root
- `docs/` -> 仓库拥有的 guidance、deep dives 与 maintainer notes
- `tests/` -> 仓库级回归与 acceptance coverage
- `examples/` -> 可运行 examples 与 integration samples
- `upstreams/` -> 导入的第三方源码快照或镜像
- `.local/` -> 仓库本地生成状态、scratch work 与 durable demo artifacts

## Packaging 所有权

仓库根目录的 `pyproject.toml` 只是 workspace coordinator。具体 packages 拥有自己的 package-local metadata：

- 根 `pyproject.toml` -> workspace metadata、共享开发者配置与 family 声明
- `packages/framework-core/pyproject.toml` -> `weavert` runtime package metadata
- `packages/framework-packs/` 下每个具体 package 都拥有自己的 local metadata
- `packages/toolchain/starter/pyproject.toml` -> `weavert-starter` CLI metadata
- `packages/product-kits/` 与 `packages/toolchain/` 下每个具体 package 都拥有自己的 local metadata

## 后续抽取 guardrail

做 follow-on extraction 改动时，应把代码放进相应 workspace families，而不是把新的 non-core modules 恢复到 `packages/framework-core/src/weavert/` 下。

落地前请检查：

1. 先决定新代码属于哪个 package family
2. 如新增具体 package，同步补齐该 family 下的 package-local metadata
3. 保持根 `pyproject.toml` 只是 workspace coordinator，而不是回退为唯一的可发布 package 定义
4. 可运行仓库 examples 放在 `examples/`，导入第三方代码放在 `upstreams/`，仓库本地 scratch state 放在 `.local/`
5. 运行 `python3 packages/toolchain/scripts/check_workspace_layout.py`

## 文档经验法则

- 根 `README.md` 是 landing page
- `docs/README.md` 是 docs home
- end-user guides 与 maintainer notes 分开
- examples 保持为验证索引，而不是主要 getting-started 路径

## 下一步

- 如果仓库迁移会改变公开边界或打包假设，读 `migration-notes.md`
- 如果仓库改动还需要证据链或 follow-up ledger，进入 `validation-findings.md`
- 在把布局规则变成 contributor workflow 变更前，先打开 `../../../CONTRIBUTING.zh-CN.md`

## 另见

- `../README.md`
- `../reference/workspace-layout.md`
- `migration-notes.md`
