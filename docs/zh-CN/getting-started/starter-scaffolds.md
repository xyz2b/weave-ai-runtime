# Starter 脚手架

如果你的目标是创建自己的 WeaveRT 项目，请在复制 `examples/` 之前先从这里开始。

Starter 目录存在的目的，是提供：

- 官方、最小、可运行的起点
- 规范的 `weavert` 公开导入方式
- 规范的 `.weavert/` 工作区布局
- 清晰区分采纳路径与验证路径

## 适合谁？

- 正在选择最适合自己采纳路径的官方 starter scaffold 的用户。

## 前置条件

- 先完成 `installation.md`
- 如果你想先走最小可运行路径再比较各个 scaffold 形状，先读 `quickstart.md`

## 官方生成路径

```bash
weavert-starter list
weavert-starter generate minimal-project ./my-weavert-app
weavert-starter generate headless-workflow ./my-headless-runner
weavert-starter generate live-smoke ./my-live-smoke
```

如果目标目录已存在而你想重新生成 scaffold，请加上 `--force`。

## 应该选哪个 scaffold？

### `minimal-project`

适合：

- 你正在启动一个普通的 WeaveRT 项目
- 你想要项目本地 tool 与 agent 发现机制的最小循环
- 你想先建立一个不依赖 provider 凭据的离线 baseline

它会提供：

- `RuntimeConfig.for_ordinary_workflow(...)`
- `.weavert/agents/` 与 `.weavert/tools/`
- `weavert_testing.ScriptedModelClient`
- 一个很小的 `app.py` 入口

### `headless-workflow`

适合：

- 你想要一个 CI 或脚本化工作流运行器
- 你更偏好 report-oriented helpers，而不是 app-shell UX
- 你想在 live 集成前先确认一个确定性的工作流契约

它会提供：

- `run_workflow_test(...)`
- `final_assistant_text(...)`
- `latest_tool_outcome(...)`
- `terminal_failure(...)`

### `live-smoke`

适合：

- 你想做一个 provider-backed readiness 检查
- 你在更重的集成之前需要 route preflight
- 你想让 live 失败保持显式，而不是退回 scripted 行为

它会提供：

- `RuntimeConfig.for_headless_live(...)`
- `preflight_default_model_route()`
- 一个明确的 live-only 入口

## Starter 与 examples 的区别

- starter scaffolds = 采纳路径
- examples = 验证路径

当你想开始自己的项目时，用 starter。
当你想验证某个特定 runtime seam 或 workflow boundary 时，用 examples。

## 下一步

1. 先运行一次生成后的入口
2. 在 `.weavert/` 下加入自己的项目本地定义
3. 去 `../../../examples/README.zh-CN.md` 验证扩展 seam
4. 只有在确实需要时，再进入 host binding 或 scenario packs

## 另见

- `quickstart.md`
- `../guides/build-your-first-project.md`
- `../../../examples/README.zh-CN.md`
