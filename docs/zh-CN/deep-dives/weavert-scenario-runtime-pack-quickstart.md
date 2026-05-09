# WeaveRT Scenario Runtime Pack 快速开始

> 文档说明：这是 scenario-pack 激活的 deep-dive 速记版。普通路径请先读 `docs/zh-CN/concepts/packages-and-scenario-packs.md` 与 `docs/zh-CN/guides/use-scenario-packs.md`。

## 对应主文档

- Package / scenario-pack concepts -> `docs/zh-CN/concepts/packages-and-scenario-packs.md`
- Activation guide -> `docs/zh-CN/guides/use-scenario-packs.md`
- Package system -> `docs/zh-CN/architecture/package-system.md`

## 1. 先记住的基线

Scenario runtime packs：

- 不属于默认 distribution baseline
- 不会自动进入 runtime
- 必须先通过 `RuntimeConfig.extra_package_manifests` admit
- 只有在 `RuntimeConfig.requested_packages` 里请求后才会 active

## 2. 一个规范激活模板

最小激活模板需要：

- manifest provider import
- `enabled_packages`
- `requested_packages`

## 3. Profile 选择矩阵

- coding 最接近 repo-oriented assistants
- chat 默认会避免把 coding-oriented mutation surfaces 带进来
- local assistant 仍依赖 host-bound bridge facets 才能做 live browser / OS / PIM 行为
- shared-packages-only 适合你已经有自己的 shell 或主 agent，只想复用桥接能力

## 4. 每种 profile 真正带来什么

- coding：工作区工具、planner / reviewer 风格角色，以及 git / workspace intelligence shared surfaces
- chat：retrieval、citations 与 response-quality workflows
- local assistant：更强 host-centric posture，与多种 bridge expectations 配合
- shared packages only：只引入可复用 capability bridges，不附带完整 scenario workflow profile

## 5. 如何确认 package 真的进入 runtime

你需要分别确认：

- package candidate 已 admitted
- package 已真正进入 resolved graph
- 预期的 profile metadata 或 capability payload 已出现

可通过 projected manifest metadata 与 capability payload 检查。

## 6. Local-assistant bridge 警告

Local-assistant package 可以提供：

- staged bridge tools
- bridge expectations
- host-facing capability contracts

但不会替你神奇提供：

- live browser authority
- live OS authority
- live PIM authority

这些最终都仍由 host 决定。

## 7. 常见错误

- admit 了 manifest，却没有 request package
- request 了 scenario pack，却没有启用它推荐的 first-party packages
- 把 scenario pack 当成新 runtime mode，而不是 package selection
- 以为 local-assistant bridge packages 会秘密接管 browser / OS / PIM 执行
- 把 shared packages 与 scenario packs 当成同一种抽象

## 8. 接下来读什么

- 架构边界 -> `docs/zh-CN/deep-dives/weavert-scenario-runtime-pack-architecture.md`
- 主用户 guide -> `docs/zh-CN/guides/use-scenario-packs.md`
- package surfaces 与扩展选择 -> `docs/zh-CN/deep-dives/weavert-user-extension-guide.md`
- 更完整 app sample -> `examples/apps/code_assistant/app.py`
