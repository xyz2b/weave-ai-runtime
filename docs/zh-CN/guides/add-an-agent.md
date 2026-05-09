# 添加 Agent

## 适合谁？

需要一个具名 prompt 角色的用户，例如 reviewer、planner 或 support specialist。

## 前置条件

- 一个包含 `.weavert/agents/` 的可运行项目
- 一个应在多个 sessions 或 workflows 中复用的清晰角色

## Agent 应该拥有的内容

Agent 应负责角色行为、prompt 身份和 scope posture。
它不应成为隐藏那些本该属于 tools 的执行逻辑的地方。

## 步骤

1. 创建 `.weavert/agents/reviewer.md`
2. 给 agent 一个名字、描述，以及它真正需要的 tools
3. 让指令聚焦在角色、输出和决策姿态上
4. 从你的项目或其他 runtime surface 调用这个 agent

最小示例：

```md
---
name: reviewer
description: Review a proposed change and return a terse verdict.
tools:
  - check_file
---
You are the reviewer for this workspace.
Inspect the evidence you need, then return a short verdict and one recommendation.
```

## 一个好的 agent 设计检查表

- tool 池要明显小于 “everything”
- 在 prompt 里明确成功标准
- 把结构化工作交给 tools，把可复用流程交给 skills
- 只有当更窄的子角色真的有帮助时，才做 delegation

## Hook 说明

Agent-owned hooks 不是普通推荐扩展路径。
如果你需要生命周期注入，优先用：

- skill hooks
- runtime 或 session hook registration
- bound-host hook registration

## 预期结果

Runtime 能按名称发现这个 agent，并把它作为一个独立的、由 prompt 拥有的角色来路由工作。

## 下一步

用 `python3 -B -m examples.agents.file_backed_agent_demo` 或 `python3 -B -m examples.agents.scoped_agent_delegation_demo` 验证这个 seam。

## 另见

- `../concepts/tools-agents-skills.md`
- `add-a-skill.md`
- `../../../examples/agents/workspace/.weavert/agents/release-reviewer.md`
