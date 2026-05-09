# Coding Workflow Fixture

这个工作区有意保持很小，也有意保留了一个故障。

## 这个 fixture 是做什么的

- 给普通 coding workflow demo 提供一个小型的工作区本地目标
- 让任务保持在 ordinary extension path 上，通过本地 `.weavert/` definitions 运行
- 让离线验证与 live smoke 共用同一个 fixture

## 这个 fixture 支持的任务

Coding workflow demo 会要求 runtime：

- 通过工作区本地 `.weavert/` definitions 检查 greeting bug
- 更新默认 greeting，使测试通过
- 运行 `python3 -m unittest discover -s tests`
- 通过本地 `review-change` skill 做一次 review pass

## 验证说明

默认离线 demo 与可选的 `--live` smoke path 使用的是同一个任务、fixture 与成功标准。

## 另见

- `../../../README.zh-CN.md`
- `../../../../docs/zh-CN/guides/build-your-first-project.md`
- `../../../../docs/zh-CN/guides/testing-and-observability.md`
