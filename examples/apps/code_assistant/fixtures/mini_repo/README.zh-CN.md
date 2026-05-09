# Mini Repo Fixture

这个仓库被有意设计得很小，也有意保留了一些缺陷。

## 这个 fixture 是做什么的

- 给高级 code-assistant sample 提供一个很小、可变的工作区
- 让任务足够小，从而保持验证输出可读
- 把 app-owned shell layer 与 scenario-pack-owned workflow surfaces 分开

## 这个 fixture 支持的任务

默认 live demo task 会要求 code assistant：

- 修复默认 greeting，使测试通过
- 在 `notes/live_demo.md` 下加一行说明
- 运行单元测试
- 请求 reviewer 与 verifier child-agent passes

## 所有权说明

这个 fixture 的 `.weavert/` 目录现在只保留 app-owned shell layer。
官方 coding scenario pack 提供可复用的 `coding-planner`、`reviewer`、`verifier`、`coding-loop`、`review-change`、`verify-change`、`task-discipline` 与 `repo-onboard` workflow surfaces。

## 另见

- `../../README.zh-CN.md`
- `../../../../README.zh-CN.md`
- `../../../../../packages/product-kits/coding/README.zh-CN.md`
- `../../../../../docs/zh-CN/guides/use-scenario-packs.md`
