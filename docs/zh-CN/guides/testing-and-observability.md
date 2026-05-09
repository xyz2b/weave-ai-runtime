# 测试与可观测性

## 适合谁？

希望在继续增加表面积之前，先确认某个 runtime 扩展或 workflow 确实可用的用户。

## 前置条件

- 一个已能运行的项目或 example
- 愿意一次只验证一个 seam

## 推荐的验证阶梯

先从窄范围开始，只有当前一层稳定后再扩大范围：

1. seam basics
2. user-centric validation
3. semantic demos
4. project workflows
5. live smoke
6. advanced host-bound apps

这条可运行索引位于 `../../../examples/README.zh-CN.md`。

## 为什么确定性和离线检查应放在前面

离线验证通常更能回答框架层问题，例如：

- tool 是否被发现？
- permission denial 行为是否正确？
- helper-owned 与 caller-owned session 行为是否符合预期？
- package 是仅被 admitted，还是已经真正 activated？

Live 验证当然有用，但它会带入凭据、provider 以及开放式模型波动。

## 值得使用的 runtime-owned helper surfaces

在回答常见问题时，优先使用 runtime-owned helper surfaces，而不是手写 transcript 解析。
常用 helpers 包括：

- `final_assistant_text(...)`
- `latest_tool_outcome(...)`
- `latest_skill_outcome(...)`
- `terminal_failure(...)`
- `child_summary(...)`

它们让你在不把每次 workflow 检查都变成自定义 transcript parsing 的前提下，回答常见 post-run 问题。

## Workflow observability

共享 workflow observability model 会在 turn streams、child-run results、host events 和 workflow reports 之间提供一个统一的 runtime-owned 视图。
有用的概念包括：

- lifecycle status，如 `running`、`completed`、`blocked`、`failed`
- outcome，如 `succeeded`、`degraded`、`failed`
- diagnostic severity，如 `info`、`advisory`、`blocking`

如果你需要低层真相，继续看原始 turn streams 与 durable records。
如果你只想得到一条稳定的高层答案来判断 workflow 健康状态，使用共享模型。

## 预期结果

你应该能回答下面这些问题：

- 正确的 tool 是否运行了？
- 谁拥有 session 生命周期？
- durable state 是否被写入？
- package 是仅被 admitted，还是已经 active？
- route failure 是凭据问题还是 runtime 问题？

## 实用命令

```bash
.venv/bin/python -m pytest tests/test_runtime_extension_demos.py
python3 -B -m examples.tools.guarded_tool_demo
python3 -B -m examples.runtime.assembly_diagnostics_demo
python3 -B -m examples.projects.coding_workflow_demo
```

## 下一步

- 回到你刚修改的 guide，并重新运行对应的聚焦验证路径
- 当你需要稳定的字段级 observability contract 时，进入 `../reference/workflow-observability.md`
- 如果你在维护 repo-level 验证证据，读 `../maintainers/validation-findings.md`

## 另见

- `../../../examples/README.zh-CN.md`
- `register-hooks.md`
- `../deep-dives/weavert-workflow-observability.md`
- `../reference/workflow-observability.md`
- `../maintainers/validation-findings.md`
