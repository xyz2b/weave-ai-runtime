# WeaveRT Scenario Runtime Pack 架构

> 文档说明：这是 scenario-pack 边界的 deep-dive 参考。普通路径请先读 `docs/zh-CN/concepts/packages-and-scenario-packs.md`、`docs/zh-CN/architecture/package-system.md` 与 `docs/zh-CN/guides/use-scenario-packs.md`。

## 对应主文档

- Package / scenario-pack concepts -> `docs/zh-CN/concepts/packages-and-scenario-packs.md`
- Package system -> `docs/zh-CN/architecture/package-system.md`
- Activation guide -> `docs/zh-CN/guides/use-scenario-packs.md`

这篇文档重点回答：

- scenario pack 拥有什么，app 仍拥有些什么
- shared packages 与 scenario packs 的区别
- 本仓库有哪些 profile families
- 哪些内容由 package selection 激活，哪些内容属于 host binding

## 1. 五层心智模型

一个 scenario pack 可以：

- 推荐 profile posture
- 依赖 shared packages
- 发布 workflow guidance 与 metadata

一个 scenario pack 不能：

- 变成最终 host、provider 或 permission owner

## 2. 所有权矩阵

- shared packages 回答：“这个能力是否跨产品形态复用？”
- scenario packs 回答：“这种产品 profile 默认应该长什么样？”
- app wiring 回答：“这个部署最终真正交付什么？”

## 3. Distribution、scenario pack 与 `.weavert/` 必须分离

不要把这三层混成一层，否则 host ownership 与 package activation 都会变得含混。

## 4. Shared packages 与 scenario packs 的区别

适合做 shared packages 的能力例子：

- retrieval
- browser / local OS / PIM bridges
- coding-oriented git 或 workspace inspection

它们都不应在每个 profile 里各自重写一遍。

## 5. 本仓库里的参考 profile shapes

- coding
- chat
- local assistant

## 6. Activation 契约

关键配置槽位：

- `RuntimeConfig.distribution`
- `RuntimeConfig.enabled_packages`
- `RuntimeConfig.disabled_packages`
- `RuntimeConfig.extra_package_manifests`
- `RuntimeConfig.requested_packages`

必须牢记：

- scenario packs 不属于默认 distribution baselines
- runtime 不会自动加载它们
- 推荐 first-party packages 仍需由 app 自己选择
- 只请求 scenario pack，并不会神奇地把无关 tools、agents 或 skills 一起带进来

检查入口：

- `weavert.services.metadata["package_manifests"]`
- `RuntimeServices.require_capability(...)`

## 7. App-owned wiring 仍是最终权威

最终仍由 app 拥有的内容包括：

- provider route selection
- transcript、memory 与 job store selection
- host binding 与 host UX
- 最终 permission composition
- browser / OS / PIM live execution adapters
- deployment-specific audit 与 approval posture

Package 可以声明 bridge expectations，但 host 仍决定是否真的存在这些 live authorities。

## 8. 相关文档

- `docs/zh-CN/concepts/packages-and-scenario-packs.md`
- `docs/zh-CN/architecture/package-system.md`
- `docs/zh-CN/guides/use-scenario-packs.md`
- `docs/zh-CN/deep-dives/weavert-scenario-runtime-pack-quickstart.md`
- `examples/README.zh-CN.md`
