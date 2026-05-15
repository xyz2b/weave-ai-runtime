# WeaveRT 文档

[English](../README.md) | 简体中文

这是根目录 [README.zh-CN.md](../../README.zh-CN.md) 之后的中文文档首页。
请把文档当成一条分层旅程，而不是“一个落地页 + 一堆很长的文件”。

1. GitHub 落地页 -> WeaveRT 是什么、为什么存在
2. Getting started -> 第一次成功运行
3. Concepts -> 运行时模型与扩展边界
4. Guides -> 如何解决一个具体任务
5. Architecture / reference / maintainers -> 系统如何构建与维护

Starter 是采纳路径。
Examples 是验证路径。

## 从这里开始

- 第一次了解 WeaveRT：[introduction/what-is-weavert.md](introduction/what-is-weavert.md)
- 需要首轮运行：[getting-started/quickstart.md](getting-started/quickstart.md)
- 想走官方 starter 路径：[getting-started/starter-scaffolds.md](getting-started/starter-scaffolds.md)
- 想在 starter 之后跑可执行验证：[../../examples/README.zh-CN.md](../../examples/README.zh-CN.md)

## 文档旅程

### 1. Introduction

- [introduction/what-is-weavert.md](introduction/what-is-weavert.md)
- [introduction/use-cases.md](introduction/use-cases.md)
- [introduction/design-principles.md](introduction/design-principles.md)

### 2. Getting Started

- [getting-started/installation.md](getting-started/installation.md)
- [getting-started/quickstart.md](getting-started/quickstart.md)
- [getting-started/starter-scaffolds.md](getting-started/starter-scaffolds.md)

### 3. Concepts

- [concepts/runtime-model.md](concepts/runtime-model.md)
- [concepts/tools-agents-skills.md](concepts/tools-agents-skills.md)
- [concepts/packages-and-scenario-packs.md](concepts/packages-and-scenario-packs.md)
- [concepts/hosts-permissions-memory.md](concepts/hosts-permissions-memory.md)
- [concepts/memory-model.md](concepts/memory-model.md)

### 4. Guides

- [guides/build-your-first-project.md](guides/build-your-first-project.md)
- [guides/choose-package-combinations.md](guides/choose-package-combinations.md)
- [guides/add-a-tool.md](guides/add-a-tool.md)
- [guides/add-an-agent.md](guides/add-an-agent.md)
- [guides/add-a-skill.md](guides/add-a-skill.md)
- [guides/integrate-openai.md](guides/integrate-openai.md)
- [guides/use-scenario-packs.md](guides/use-scenario-packs.md)
- [guides/bind-a-host.md](guides/bind-a-host.md)
- [guides/extend-the-control-plane.md](guides/extend-the-control-plane.md)
- [guides/register-hooks.md](guides/register-hooks.md)
- [guides/testing-and-observability.md](guides/testing-and-observability.md)

### 5. Architecture

- [architecture/overview.md](architecture/overview.md)
- [architecture/request-lifecycle.md](architecture/request-lifecycle.md)
- [architecture/package-system.md](architecture/package-system.md)
- [architecture/persistence-and-state.md](architecture/persistence-and-state.md)

### 6. Reference

- [reference/public-package-catalog.md](reference/public-package-catalog.md)
- [reference/runtime-config.md](reference/runtime-config.md)
- [reference/workspace-layout.md](reference/workspace-layout.md)
- [reference/memory-configuration.md](reference/memory-configuration.md)
- [reference/hook-registration.md](reference/hook-registration.md)
- [reference/workflow-observability.md](reference/workflow-observability.md)
- [reference/glossary.md](reference/glossary.md)

### 7. Maintainers

- [maintainers/repository-layout.md](maintainers/repository-layout.md)
- [maintainers/migration-notes.md](maintainers/migration-notes.md)
- [maintainers/validation-findings.md](maintainers/validation-findings.md)

## 按目标选择路径

- 我想先跑通最小成功项目 -> [getting-started/starter-scaffolds.md](getting-started/starter-scaffolds.md)
- 我想做第一个真实项目 -> [guides/build-your-first-project.md](guides/build-your-first-project.md)
- 我需要公开包目录 -> [reference/public-package-catalog.md](reference/public-package-catalog.md)
- 我需要按场景选包建议 -> [guides/choose-package-combinations.md](guides/choose-package-combinations.md)
- 我想理解运行时模型 -> [concepts/runtime-model.md](concepts/runtime-model.md)
- 我想理解记忆行为 -> [concepts/memory-model.md](concepts/memory-model.md)
- 我想扩展工具、智能体或技能 -> [guides/add-a-tool.md](guides/add-a-tool.md)、[guides/add-an-agent.md](guides/add-an-agent.md)、[guides/add-a-skill.md](guides/add-a-skill.md)
- 我想处理宿主、Hook 或控制面行为 -> [guides/bind-a-host.md](guides/bind-a-host.md)、[guides/extend-the-control-plane.md](guides/extend-the-control-plane.md)、[guides/register-hooks.md](guides/register-hooks.md)
- 我想验证真实工作流 -> [../../examples/README.zh-CN.md](../../examples/README.zh-CN.md)
- 我维护这个仓库 -> [maintainers/repository-layout.md](maintainers/repository-layout.md)

## Deep Dives

上面的分层结构是主阅读路径。
只有在主文档已经回答了公开层面的 “what” 和 “how” 之后，再进入 deep dives 查看更底层的边界台账。

可用入口：

- 运行时与集成边界 -> [deep-dives/weavert-integration-guide.md](deep-dives/weavert-integration-guide.md)
- 定义与扩展边界 -> [deep-dives/weavert-definition-authoring-guide.md](deep-dives/weavert-definition-authoring-guide.md)
- 包与场景包边界 -> [deep-dives/weavert-scenario-runtime-pack-architecture.md](deep-dives/weavert-scenario-runtime-pack-architecture.md)
- 宿主、Hook 与控制面边界 -> [deep-dives/weavert-control-plane-extension-guide.md](deep-dives/weavert-control-plane-extension-guide.md)
- 完整索引 -> [deep-dives/README.md](deep-dives/README.md)
- framework-pack 文档索引 -> [framework-packs/README.md](framework-packs/README.md)

## Maintainer 台账

仅面向维护者的验证与迁移台账位于：

- [maintainers/validation-findings.md](maintainers/validation-findings.md)
- [maintainers/migration-notes.md](maintainers/migration-notes.md)
- [maintainers/repository-layout.md](maintainers/repository-layout.md)
