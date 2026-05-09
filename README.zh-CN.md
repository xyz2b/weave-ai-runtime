<p align="center">
  <img src="docs/logo.png" alt="WeaveRT logo" width="160">
</p>

[English](README.md) | 简体中文

# WeaveRT

用于构建 Agent 系统的可组合 AI 运行时框架，覆盖工具、智能体、技能、宿主、记忆、工作流包与场景包。

## WeaveRT 是什么？

WeaveRT 是一个用于构建和运行 Agent 系统的运行时框架。
它提供稳定的运行时内核，以及清晰的扩展边界，覆盖工具、智能体、技能、宿主、权限、记忆、工作流包和场景包。

它不是一个预设好的单体助手应用。
你可以先从一个很小的项目内工作流起步，再逐步扩展到 coding、chat 或 local-assistant 产品，而不用重写运行时模型。

## 为什么是 WeaveRT？

- 构建在运行时之上，而不是单条 prompt 之上。
- 组合工具、智能体、技能与包，同时保持所有权边界清晰可见。
- 让宿主集成、权限与持久状态保持显式。
- 从最小脚手架起步，再逐步扩展到更完整的工作流和应用。

## 快速开始

默认的第一条路径是 starter，而不是 `examples/`。
Starter 是采纳路径，examples 是验证路径。

从本地仓库副本开始，最短路径如下：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e packages/framework-core
python -m pip install -e packages/toolchain/starter
python -m pip install -e packages/toolchain/testing
weavert-starter generate minimal-project ./my-weavert-app
cd my-weavert-app
python -m pip install -e .
python app.py
```

首轮运行应看到这些锚点：

- `preset: ordinary-workflow`
- `assistant: The scaffold is ready...`
- `status: ok`

## 从这里开始

- 文档首页：[docs/zh-CN/README.md](docs/zh-CN/README.md)
- 第一次运行：[docs/zh-CN/getting-started/quickstart.md](docs/zh-CN/getting-started/quickstart.md)
- 官方 starter 路径：[docs/zh-CN/getting-started/starter-scaffolds.md](docs/zh-CN/getting-started/starter-scaffolds.md)
- 可运行的验证路径：[examples/README.zh-CN.md](examples/README.zh-CN.md)

## 按目标选择路径

- 我想先跑通最小成功项目 -> [docs/zh-CN/getting-started/starter-scaffolds.md](docs/zh-CN/getting-started/starter-scaffolds.md)
- 我想做第一个真实项目 -> [docs/zh-CN/guides/build-your-first-project.md](docs/zh-CN/guides/build-your-first-project.md)
- 我想理解运行时模型 -> [docs/zh-CN/introduction/what-is-weavert.md](docs/zh-CN/introduction/what-is-weavert.md) 和 [docs/zh-CN/concepts/runtime-model.md](docs/zh-CN/concepts/runtime-model.md)
- 我想扩展工具、智能体或技能 -> [docs/zh-CN/guides/add-a-tool.md](docs/zh-CN/guides/add-a-tool.md)、[docs/zh-CN/guides/add-an-agent.md](docs/zh-CN/guides/add-an-agent.md)、[docs/zh-CN/guides/add-a-skill.md](docs/zh-CN/guides/add-a-skill.md)
- 我想做宿主、Hook 或控制面集成 -> [docs/zh-CN/guides/bind-a-host.md](docs/zh-CN/guides/bind-a-host.md)、[docs/zh-CN/guides/extend-the-control-plane.md](docs/zh-CN/guides/extend-the-control-plane.md)、[docs/zh-CN/guides/register-hooks.md](docs/zh-CN/guides/register-hooks.md)
- 我想验证真实工作流 -> [examples/README.zh-CN.md](examples/README.zh-CN.md)
- 我是仓库维护者 -> [docs/zh-CN/maintainers/repository-layout.md](docs/zh-CN/maintainers/repository-layout.md) 和 [docs/zh-CN/maintainers/migration-notes.md](docs/zh-CN/maintainers/migration-notes.md)

## 示例

- 基础 seam 与验证路径：[examples/README.zh-CN.md](examples/README.zh-CN.md)
- 普通 coding 工作流验证：[examples/README.zh-CN.md](examples/README.zh-CN.md)
- 高级宿主集成样例：[examples/apps/code_assistant/README.zh-CN.md](examples/apps/code_assistant/README.zh-CN.md)

除非你是在专门评估框架 seam 或验证证据，否则先生成 starter。

## 架构与参考

- 架构概览：[docs/zh-CN/architecture/overview.md](docs/zh-CN/architecture/overview.md)
- 请求生命周期：[docs/zh-CN/architecture/request-lifecycle.md](docs/zh-CN/architecture/request-lifecycle.md)
- RuntimeConfig 参考：[docs/zh-CN/reference/runtime-config.md](docs/zh-CN/reference/runtime-config.md)
- 完整文档索引：[docs/zh-CN/README.md](docs/zh-CN/README.md)

## 当前状态

WeaveRT 仍在持续开发中。
文档按分层旅程组织：
landing page -> getting started -> concepts -> guides -> architecture/reference/maintainers。

## 贡献

开发与提交流程见 [CONTRIBUTING.zh-CN.md](CONTRIBUTING.zh-CN.md)。
社区行为规范见 [CODE_OF_CONDUCT.zh-CN.md](CODE_OF_CONDUCT.zh-CN.md)，漏洞报告说明见 [SECURITY.zh-CN.md](SECURITY.zh-CN.md)。

## License

协议为 Apache-2.0，详见 [LICENSE](LICENSE)。
