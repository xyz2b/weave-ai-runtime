# Workflow 可观测性参考

这页汇总 runtime 暴露的共享 workflow observability model。

## 适合谁？

- 已理解整体工作流、现在需要稳定查询页的读者。

## 前置条件

- 先读对应的 guide 或 concept 页面
- 把这页当成 reference sheet，而不是第一站教程

## 核心对象

- `WorkflowRunIdentity`
  - 稳定的 `run_id`、`session_id` 与 `turn_id`
- `WorkflowRunLinkage`
  - parent run 或 parent turn 的关联
- `WorkflowRunObservability`
  - run kind、lifecycle status、outcome、linkage 与 structured diagnostics
- `WorkflowDiagnostic`
  - diagnostic severity 与 outcome 语义
- `WorkflowObservationEvent`
  - 供 hosts 与 streams 使用的事件形投影

## Lifecycle status 词汇

- `running`
- `completed`
- `max_turns`
- `blocked`
- `interrupted`
- `failed`
- `denied`
- `stopped`

## Outcome 词汇

- `running`
- `succeeded`
- `degraded`
- `blocked`
- `interrupted`
- `failed`

## Diagnostic severity 词汇

- `info`
- `advisory`
- `blocking`

## 模型出现在哪里

### Turn streams

Workflow observations 会出现在 turn-stream events 中，例如：

- `event.workflow_observation`
- `event.metadata["workflow_observation"]`

### Child-run projections

Child-run helpers 也通过投影记录与结果暴露同一套模型。

### Host bridge

Runtime 会通过 `HostRuntime.emit_extension_event(...)`，在命名空间 `weavert.workflow` 下发出 workflow extension events。
典型事件类型包括：

- `workflow.started`
- `workflow.terminal`
- `workflow.child.updated`

### Workflow reports 与 helpers

`WorkflowRunReport` 以及 `terminal_failure(...)`、`child_summary(...)`、`resolve_workflow_run_observability(...)` 等 helpers 都会保留这套共享模型。

## 正确理解这套模型

当你需要 runtime-owned 的统一答案来回答这些问题时，用共享模型：

- 这是哪个 workflow run？
- 它处于什么状态？
- 它是健康、降级、阻塞还是失败？

如果你需要更低层的真相，就继续使用原始 turn streams、transcripts 或 durable child-run records。

## 下一步

- 若需要围绕这些字段的更广泛验证工作流，回到 `../guides/testing-and-observability.md`
- 若想把这些 observability 术语映射回 runtime phases，读 `../architecture/request-lifecycle.md`

## 另见

- `../guides/testing-and-observability.md`
- `../architecture/request-lifecycle.md`
- `../deep-dives/weavert-workflow-observability.md`
