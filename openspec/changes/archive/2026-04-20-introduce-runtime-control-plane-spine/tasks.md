## 1. Runtime Services Foundations

- [x] 1.1 新增 `runtime_services` 模块，定义 `RuntimeServices` 聚合对象与 control-plane service 协议
- [x] 1.2 为 hooks、permissions、elicitation、memory、compaction、host、task、transcript 提供默认或 no-op service 占位实现

## 2. Kernel Assembly Refactor

- [x] 2.1 重构 `RuntimeKernel`/`RuntimeAssembly` 装配流程，先构建 control-plane service graph，再构建 execution stack
- [x] 2.2 更新 `BoundHostRuntime` 与相关装配入口，使其持有共享的 runtime service graph

## 3. Execution Plane Integration

- [x] 3.1 让 `TurnEngine` 与 tool execution 路径通过共享 runtime contract 消费 control-plane services，而不是依赖局部 callback wiring
- [x] 3.2 让 `SessionController`、`AgentRuntime`、`SkillRuntime` 接入共享 control-plane contract

## 4. Context Assembly and Compatibility

- [x] 4.1 将当前 prompt composition 边界提升为 control-plane aware 的上下文装配步骤
- [x] 4.2 增加兼容 adapter 与回归测试，确保现有 query/session/runtime tests 在 spine 重构期间保持可运行
