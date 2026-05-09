# Deep Dives

这些文件是详细参考资料，不是默认文档旅程。
请在完成 `../README.md` 对应的主阅读路径后再使用它们。

## 什么时候使用这个目录

- 你已经读过公开 guide 或 concept 页，现在需要更底层的边界台账
- 你正在详细评估框架 seams 与所有权
- 你正在维护或扩展仓库，需要更深的实现上下文

## 从你的问题出发

- App、assembly、session、turn 与 control-plane 层之间是谁拥有谁？
  - [current-system-architecture.md](current-system-architecture.md)
- 应用或 host 应在哪一层与 runtime 集成？
  - [weavert-integration-guide.md](weavert-integration-guide.md)
- 在开始改基础设施前，应该先用哪种扩展层？
  - [weavert-user-extension-guide.md](weavert-user-extension-guide.md)
- Tools、agents 与 skills 的稳定契约是什么？
  - [weavert-definition-authoring-guide.md](weavert-definition-authoring-guide.md)
- Host、permissions、elicitation、hooks 与 context contributors 如何分责？
  - [weavert-control-plane-extension-guide.md](weavert-control-plane-extension-guide.md)
- 更低层的 hook 注册模型是什么？
  - [weavert-hook-configuration-platform.md](weavert-hook-configuration-platform.md)
- Scenario packs 与 shared packages 如何放进 package composition？
  - [weavert-scenario-runtime-pack-architecture.md](weavert-scenario-runtime-pack-architecture.md)
- 我已经理解 package 边界，只想要最短激活提醒
  - [weavert-scenario-runtime-pack-quickstart.md](weavert-scenario-runtime-pack-quickstart.md)
- 分层 memory 如何划分 durable artifacts 与 diagnostics？
  - [layered-memory-weavert-v2.md](layered-memory-weavert-v2.md)
- Streams、reports、host events 与 child runs 之间共享的 workflow observability model 是什么？
  - [weavert-workflow-observability.md](weavert-workflow-observability.md)
- OpenAI adapter 的 transport、schema 与 failure-mode 细节是什么？
  - [weavert-openai-responses-adapter.md](weavert-openai-responses-adapter.md)

## 这个目录不是什么

- 不是默认 getting-started 路径
- 不是第一次学习某个任务的最佳入口
- 不是 maintainer-only validation ledgers 所在地

## Maintainer 台账

维护者导向的迁移与验证台账位于 `../maintainers/`：

- [../maintainers/migration-notes.md](../maintainers/migration-notes.md)
- [../maintainers/validation-findings.md](../maintainers/validation-findings.md)
