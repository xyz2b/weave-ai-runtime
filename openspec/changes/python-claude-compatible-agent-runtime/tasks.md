## 1. Runtime 基础设施

- [ ] 1.1 定义 runtime kernel、session runtime、turn engine、registries、memory、hooks、built-ins 与 host adapters 的 Python 包结构
- [ ] 1.2 实现保持 Claude Code 兼容语义的 Python 原生 tool、agent、skill 与 hook 定义模型
- [ ] 1.3 实现 bundled、user 与 project 定义来源的 registry 加载逻辑

## 2. Session Runtime

- [ ] 2.1 实现 `SessionController`，统一处理归一化后的输入命令与事件流
- [ ] 2.2 实现主线程 `main-router` agent 及其 session routing 契约
- [ ] 2.3 实现主线程 session 的 transcript、interrupt 与 resume 状态管理

## 3. Tool System

- [ ] 3.1 实现 Claude 兼容的 tool protocol，包括 validation、permission checks、progress reporting 与 result mapping
- [ ] 3.2 实现 tool pool 装配、wildcard 解析、disallow-list 过滤与并发感知的 orchestration
- [ ] 3.3 实现默认内置 tool pack，覆盖文件、shell、web、agent、skill、task 与用户交互能力

## 4. Agent 与 Skill System

- [ ] 4.1 实现 Claude 兼容的 agent 加载与执行语义，覆盖 delegated、background 与 isolated agents
- [ ] 4.2 实现 Claude 兼容的 `SKILL.md` 发现、激活与执行语义
- [ ] 4.3 实现本次变更定义的内置 agent pack 与内置 skill pack

## 5. Memory 与 Hooks

- [ ] 5.1 实现默认文件型 memory 子系统，包括 prompt injection 与 relevant-memory retrieval
- [ ] 5.2 实现 turn 后 memory extraction 与 agent memory scopes
- [ ] 5.3 实现 Claude 兼容的 runtime hook phases，以及 host lifecycle hooks

## 6. Host Integration

- [ ] 6.1 实现 CLI、TUI、SDK 与 channel 风格集成的 host adapter interfaces
- [ ] 6.2 通过 host lifecycle hooks 串联 startup、shutdown、permission 与用户提问流程
- [ ] 6.3 提供一个最小可运行 host 集成，用于证明共享 runtime 的端到端 session execution 能力

## 7. 验证与文档

- [ ] 7.1 增加 Claude 风格 tool、agent、skill、memory 与 hook 定义的兼容性 fixtures 与测试
- [ ] 7.2 增加 routing、subagents、memory extraction 与 hook behavior 的集成测试
- [ ] 7.3 补充兼容范围、内置 runtime packs 与后续扩展点的文档
