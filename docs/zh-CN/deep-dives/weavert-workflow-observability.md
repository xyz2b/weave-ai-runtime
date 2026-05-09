# WeaveRT Workflow 可观测性

> 文档说明：这是 workflow observability 的 deep-dive 参考。普通路径请先读 `docs/zh-CN/guides/testing-and-observability.md` 与 `docs/zh-CN/reference/workflow-observability.md`。

## 对应主文档

- Testing and observability guide -> `docs/zh-CN/guides/testing-and-observability.md`
- Workflow observability reference -> `docs/zh-CN/reference/workflow-observability.md`

这篇文档主要回答：

- 哪些字段在 raw turn streams、child-run records、host events 与 workflow reports 之间具有权威性
- 哪些 lifecycle / outcome / diagnostic 术语属于稳定词汇
- runtime 如何把同一套 observability model 投影到 host bridge 与 helper APIs

## 1. 共享模型

核心类型：

- `WorkflowRunIdentity`：稳定的 `run_id`、`session_id`、`turn_id`
- `WorkflowRunLinkage`：parent run / parent turn 关联
- `WorkflowRunObservability`：共享 run kind、lifecycle status、outcome、linkage 与 structured diagnostics
- `WorkflowDiagnostic`：稳定 diagnostic severity 与 outcome 语义
- `WorkflowObservationEvent`：供 turn streams 与 host bridge 使用的事件形投影

### 1.1 稳定词汇

Lifecycle status：

- `running`
- `completed`
- `max_turns`
- `blocked`
- `interrupted`
- `failed`
- `denied`
- `stopped`

Outcome：

- `running`
- `succeeded`
- `degraded`
- `blocked`
- `interrupted`
- `failed`

Diagnostic severity：

- `info`
- `advisory`
- `blocking`

## 2. 与原始 turn streams 的关系

共享模型会出现在：

- `event.workflow_observation`
- `event.metadata["workflow_observation"]`

## 3. 与 child-run records 的关系

常见投影入口：

- `project_child_run_record(record)["workflow_observability"]`
- `project_agent_run_result(result)["workflow_observability"]`

## 4. 与 host bridge 的关系

Host bridge 使用：

- namespace：`weavert.workflow`
- schema version：`1.0`

典型 event types：

- `workflow.started`
- `workflow.terminal`
- `workflow.child.updated`

## 5. 与 workflow run reports 与结果 helpers 的关系

共享模型会进入：

- `turn_id`
- `run_id`
- `workflow_observability`
- `terminal_failure(report).workflow_observability`
- `child_summary(...).workflow_observability`
- `resolve_workflow_run_observability(...)`

## 6. 低层真相仍然优先

共享 observability model 适合给出统一高层答案。
但当你需要逐事件真相、原始 transcript 或 durable child-run records 时，仍应回到底层记录本身。
