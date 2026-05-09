# Packages 与 Scenario Packs

Packages 是 WeaveRT 在单个本地项目目录之外组合可复用 runtime 能力的方式。

## 适合谁？

- 已经理解落地页定位、现在需要核心运行时词汇的使用者。

## 前置条件

- 先读 `../introduction/what-is-weavert.md`
- 如果你想把术语和可运行路径对应起来，快速浏览 `../getting-started/quickstart.md`

## 五层心智模型

```text
Runtime distribution
  -> 选择 first-party 基线

Shared packages
  -> 可复用能力表面，如 retrieval、web、git 或 browser bridges

Scenario packs
  -> 产品画像级 guidance 与 workflow surfaces

App-owned wiring
  -> provider routes、stores、host binding、最终 package requests

Host and permission plane
  -> 部署相关的 approvals、UX 与审计姿态
```

这个模型很重要，因为它能防止某个 package 悄悄变成你的整个产品。

## First-party package 角色

当前 package family 按职责划分如下：

- core runtime：`weavert`
- framework packs
  - capability：`weavert-memory`、`weavert-team`
  - mechanism：`weavert-compaction`、`weavert-isolation`
  - integration：`weavert-openai`、`weavert-hosts-reference`、`weavert-stores-file`
  - workflow：`weavert-planning`、`weavert-devtools`、`weavert-builtin-workflows`
- product kits：coding、chat、local assistant，以及共享 common kits
- toolchain：starter 与 testing helpers

工作区视图参见 `../../../packages/README.zh-CN.md` 和 `../../../packages/framework-packs/README.zh-CN.md`。

## Shared packages

Shared packages 贡献的是可被多种产品形态复用的能力。
例如：

- retrieval
- web grounding
- git inspection
- workspace intelligence
- browser 或 local OS bridges

Shared packages 回答的问题是：“这个能力是否能跨产品复用？”

## Scenario packs

Scenario packs 是产品画像级 package。
它们回答的问题是：“这种产品形态默认应该长什么样？”

一个 scenario pack 可以：

- 推荐一套基础 tool 与 workflow posture
- 发布 workflow 导向的 agents 和 skills
- 依赖 shared packages
- 贡献 package-level guidance 与 diagnostics

一个 scenario pack 不应该：

- 拥有最终 host 集成
- 拥有最终 permission policy
- 代表整个应用拥有 provider 或 store 权威
- 替代你的 workspace-local `.weavert/` 编写层

## Packages、scenario packs 与 `.weavert/` 是三种不同层

请把这三层分开：

- distribution
  - 粗粒度的 first-party 基线，如 `weavert-core`、`weavert-default`、`weavert-full`
- scenario pack
  - coding、chat 或 local assistant 这类产品画像 package
- `.weavert/`
  - 一个项目自己的 workspace-local tools、agents 与 skills

典型栈顺序是：

1. 选择 distribution
2. 请求一个 scenario pack，以及所需的 shared packages
3. 在 `.weavert/` 下添加项目本地行为
4. 绑定你自己的 host 与最终 permission posture

## 一个有用的元数据区分

如果把 package 文档分为三类，会更容易理解：

- runtime-resolved
  - 由 runtime 决定的事实，比如 package 是否 admitted 或 active
- runtime-projected
  - runtime 从 package 中投射出来用于 inspection 的事实
- convention-only
  - package family 用来自我描述的约定词汇

也正因如此，scenario pack 可以发布 profile guidance，但不会变成 host owner。

## 激活模型

Package admission 与 activation 是显式的。
常见模式是：

- 通过 `extra_package_manifests` 提供 manifests
- 通过 `requested_packages` 按名称请求 package
- 检查已组装 runtime 的 posture

这样能让组合保持可见，而不是魔法。

## 常见 profile 路线

- coding
  - 面向工作区的工具、review loops，以及 git 和 workspace-intelligence shared surfaces
- chat
  - retrieval、引用和 response-quality 工作流表面
- local assistant
  - 更强的 host 与 approval posture，通常配合 browser 或 local-OS bridges
- 仅 shared packages
  - 当你只想要可复用 bridge，而不想采用完整的 scenario workflow profile

## 下一步

- 当你准备激活某个 profile 或一组 shared packages 时，进入 `../guides/use-scenario-packs.md`
- 如果你需要更深的激活与所有权模型，读 `../architecture/package-system.md`

## 另见

- `../guides/use-scenario-packs.md`
- `../architecture/package-system.md`
- `../deep-dives/weavert-scenario-runtime-pack-architecture.md`
