# 术语表

## 适合谁？

- 已理解整体工作流、现在需要稳定查询页的读者。

## 前置条件

- 先读对应的 guide 或 concept 页面
- 把这页当成 reference sheet，而不是第一站教程

- runtime
  - 已组装的执行框架，拥有 sessions、turns 与 runtime services
- host
  - 面向应用的集成表面，拥有生命周期与 UX 关注点
- tool
  - 一个结构化的可执行能力
- agent
  - 一个具名的、由 prompt 拥有的角色
- skill
  - 一个可复用、具名的工作流步骤
- package
  - 一个基于 manifest 的 runtime capability composition 单元
- scenario pack
  - 一个把 workflow surfaces 与 guidance 组合在一起的产品画像级 package
- session
  - 负责 transcript 与 ingress handling 的连续性容器
- turn
  - 从接纳输入到终态结果的一次执行循环
- hook bus
  - runtime 用于分发生命周期 hook registrations 的 phase-dispatch 系统
- context contributor
  - request assembly 前贡献 prompt、private 或 diagnostics context 的 package-owned sidecar
- workflow observability
  - 由 runtime 拥有的，用于描述 workflow identity、lifecycle status、outcome 与 diagnostics 的共享模型
- long-term memory
  - 用于 preferences、conventions、topics 及其他持久笔记的共享 durable memory
- agent namespace memory
  - 限定到单个 agent namespace 的 durable memory
- session memory
  - 限定到单个 session 的 continuity artifacts 与 summaries
- consolidation memory
  - 把有价值 session 结果合并回更长期 memory 的慢速后台层
- transcript truth
  - 一个 session 中实际发生了什么的 durable record
- active context
  - 为某个 turn 投影出来、模型可见的视图

## 下一步

- 如果你需要把这些术语放回主运行时叙事中，回到 `../concepts/runtime-model.md`
- 如果你的词汇问题更偏某个 seam，读 `../concepts/tools-agents-skills.md` 或 `../concepts/packages-and-scenario-packs.md`

## 另见

- `../concepts/runtime-model.md`
- `../concepts/tools-agents-skills.md`
- `../concepts/packages-and-scenario-packs.md`
- `../README.md`
