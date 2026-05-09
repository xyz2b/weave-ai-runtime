# 迁移说明

这个页面汇总维护者最需要关注的高层迁移事项。

## 适合谁？

- 正在维护这个仓库、而不是第一次采纳框架的维护者与贡献者。

## 前置条件

- 先读 `../README.md`，确保公开文档路径不被打断
- 在修改仓库时，使用 `../../../examples/README.zh-CN.md` 作为可运行验证路径

## Runtime 边界迁移

更详细的 runtime 迁移台账位于 `runtime-boundary-migration-ledger.md`。
当你需要 package-boundary、hook-surface 或 distribution 迁移细节时，从那里开始。

## 文档信息架构迁移

文档现在按分层旅程组织：

1. 根 landing page
2. getting started
3. concepts
4. guides
5. architecture、reference、maintainers

新的链接和新文档都应使用这套结构。
长篇历史材料保留在 `../deep-dives/`，而不再留在 `docs/` 根目录。
Deep dives 是次级 contract ledger，不是主要用户旅程。

## Deep-dive 到主文档的映射

- `../deep-dives/current-system-architecture.md` -> `../architecture/overview.md`、`../architecture/request-lifecycle.md`
- `../deep-dives/weavert-integration-guide.md` -> `../getting-started/quickstart.md`、`../guides/bind-a-host.md`、`../guides/integrate-openai.md`
- `../deep-dives/weavert-user-extension-guide.md` -> `../concepts/tools-agents-skills.md`、`../guides/add-a-tool.md`、`../guides/add-an-agent.md`、`../guides/add-a-skill.md`
- `../deep-dives/weavert-definition-authoring-guide.md` -> `../concepts/tools-agents-skills.md`、`../guides/add-a-tool.md`、`../guides/add-an-agent.md`、`../guides/add-a-skill.md`
- `../deep-dives/weavert-scenario-runtime-pack-architecture.md` -> `../concepts/packages-and-scenario-packs.md`、`../architecture/package-system.md`
- `../deep-dives/weavert-scenario-runtime-pack-quickstart.md` -> `../guides/use-scenario-packs.md`
- 已退役的根级 `weavert-starter-scaffolds.md` -> `../getting-started/starter-scaffolds.md`
- `../deep-dives/weavert-control-plane-extension-guide.md` -> `../guides/extend-the-control-plane.md`、`../guides/register-hooks.md`、`../guides/bind-a-host.md`
- `../deep-dives/weavert-hook-configuration-platform.md` -> `../guides/register-hooks.md`、`../reference/hook-registration.md`
- `../deep-dives/weavert-workflow-observability.md` -> `../guides/testing-and-observability.md`、`../reference/workflow-observability.md`
- `../deep-dives/weavert-openai-responses-adapter.md` -> `../guides/integrate-openai.md`
- `../deep-dives/layered-memory-weavert-v2.md` -> `../concepts/memory-model.md`、`../reference/memory-configuration.md`、`../architecture/persistence-and-state.md`

## 维护建议

- 不要让 `README.md` 再次膨胀为完整手册
- 保持 guides 以任务为导向，并尽量简洁
- 继续让 maintainer material 与 end-user docs 物理分离
- 新页面优先使用稳定、可预测的英文文件名

## 下一步

- 当你需要最权威的迁移历史时，读 `runtime-boundary-migration-ledger.md`
- 如果迁移问题本质上是 package activation 或 ownership，回到 `../architecture/package-system.md`
- 若某项迁移仍需要验证证据或 follow-up tracking，使用 `validation-findings.md`

## 另见

- `runtime-boundary-migration-ledger.md`
- `../deep-dives/README.md`
- `repository-layout.md`
- `validation-findings.md`
