## 1. 项目骨架与公共契约

- [ ] 1.1 创建 `runtime_kernel`、`session_runtime`、`turn_engine`、`registries`、`memory`、`hooks`、`builtins`、`hosts`、`tests` 的 Python 包结构
- [ ] 1.2 定义共享消息模型、turn 上下文、session 状态、执行结果与错误类型
- [ ] 1.3 定义 Claude Code 兼容的 `ToolDefinition`、`AgentDefinition`、`SkillDefinition` 与 hook payload 数据模型
- [ ] 1.4 定义 runtime 配置对象、built-in 开关配置与 host 装配入口
- [ ] 1.5 定义模型客户端抽象、流式事件抽象与 transcript 存储抽象

## 2. 定义加载与 Registry

- [ ] 2.1 实现 tool registry 的注册、覆盖、查找与冲突处理
- [ ] 2.2 实现 agent registry 的注册、覆盖、查找与内置/用户优先级规则
- [ ] 2.3 实现 skill registry 的注册、覆盖、查找与激活状态管理
- [ ] 2.4 实现 bundled、user、project 三类定义来源的统一发现流程
- [ ] 2.5 实现定义加载错误、校验错误与降级告警输出
- [ ] 2.6 实现 built-in definitions 可被 host 选择性禁用或替换的装配逻辑

## 3. Tool System 核心

- [ ] 3.1 实现 tool input schema 校验、`validateInput` 与 `checkPermissions` 执行管线
- [ ] 3.2 实现 `ToolContext`、tool progress sink 与 tool result 映射逻辑
- [ ] 3.3 实现 tool traits：`readOnly`、`concurrencySafe`、`destructive`、`interruptBehavior`
- [ ] 3.4 实现主线程与 subagent 的 tool pool 装配、wildcard 解析与 `disallowedTools` 过滤
- [ ] 3.5 实现基于只读/变更型 traits 的 tool orchestration 调度器
- [ ] 3.6 实现 tool 调用过程中断、取消与错误回传行为

## 4. Built-in Tool Pack

- [ ] 4.1 实现 `read`、`glob`、`grep` 三个只读文件探索工具
- [ ] 4.2 实现 `edit`、`write` 两个文件修改工具
- [ ] 4.3 实现 `bash`、`web_fetch`、`web_search` 三个执行与外部查询工具
- [ ] 4.4 实现 `agent`、`skill` 两个 orchestration 工具
- [ ] 4.5 实现 `task_create`、`task_get`、`task_update`、`task_list`、`task_stop` 五个任务工具
- [ ] 4.6 实现 `ask_user` 与 `sleep` 两个交互/调度工具

## 5. Session Runtime 与 Turn Engine

- [ ] 5.1 实现 `SessionController` 的主状态机与 session 生命周期
- [ ] 5.2 实现 inbound event 归一化，将用户输入、系统消息、任务通知与 host 事件统一为 session commands
- [ ] 5.3 实现 session command queue、优先级与 between-turn drain 机制
- [ ] 5.4 实现 prompt composer，支持 system prompt、memory、hooks、attachments 与运行时上下文叠加
- [ ] 5.5 实现 turn engine 的主循环、流式模型响应消费与 turn completion 逻辑
- [ ] 5.6 实现 transcript 持久化、interrupt、resume 与 turn-level 恢复逻辑

## 6. Agent System

- [ ] 6.1 实现 Claude 兼容 agent 定义加载，包括 `tools`、`skills`、`model`、`effort`、`permissionMode`、`maxTurns`、`background`、`memory`、`isolation`
- [ ] 6.2 实现内置主线程 `main-router` agent 的定义与默认装配
- [ ] 6.3 实现 `main-router` 的 routing contract：直接回答、直接调 tool、调用 skill、委派 subagent
- [ ] 6.4 实现 `general-purpose`、`explore`、`plan`、`verification` 四个内置 agents
- [ ] 6.5 实现 subagent 的工具裁剪、skill 裁剪、权限上下文继承与独立执行限制
- [ ] 6.6 实现 background subagent 生命周期、状态跟踪与主线程通知
- [ ] 6.7 为 `isolation` 预留 `none`、`worktree`、`remote` 执行接口与最小默认行为

## 7. Skill System

- [ ] 7.1 实现 `SKILL.md` 发现流程与目录优先级规则
- [ ] 7.2 实现 skill frontmatter 解析，覆盖 description、model、effort、allowed-tools、hooks、context、agent、paths、user-invocable
- [ ] 7.3 实现 path-scoped/conditional skill activation 逻辑
- [ ] 7.4 实现 inline skill 执行流程，将 skill prompt 注入当前会话
- [ ] 7.5 实现 forked skill 执行流程，通过专用 agent context 执行 skill
- [ ] 7.6 实现内置 `verify`、`debug`、`stuck`、`batch`、`simplify`、`remember` 六个 skills

## 8. Memory Subsystem

- [ ] 8.1 实现默认文件型 memory provider 与 memory path 解析规则
- [ ] 8.2 实现 `MEMORY.md` 入口加载、截断与 prompt injection
- [ ] 8.3 实现 relevant memory retrieval，在 turn 前筛选并注入相关 memories
- [ ] 8.4 实现主线程 turn 结束后的自动 memory extraction 流程
- [ ] 8.5 实现 agent memory scopes：`user`、`project`、`local`
- [ ] 8.6 实现 memory 目录读写边界与与普通工作目录的隔离保护

## 9. Hook System

- [ ] 9.1 实现统一 hook bus、hook 注册表与 hook payload schema
- [ ] 9.2 实现 Claude 兼容 runtime hook phases：`SessionStart`、`UserPromptSubmit`、`PreToolUse`、`PostToolUse`、`PostToolUseFailure`、`Stop`、`SubagentStop`、`SessionEnd`
- [ ] 9.3 实现扩展 runtime hook phases：`Notification`、`Elicitation`、`ElicitationResult`、`PreCompact`、`PostCompact`
- [ ] 9.4 实现 hook 对 runtime flow 的影响能力：追加 context、更新输入、阻止 continuation、通知、elicitation 返回
- [ ] 9.5 实现 host lifecycle hooks：startup、ready、shutdown
- [ ] 9.6 实现从 settings/frontmatter/host 装配 hook 的统一入口

## 10. Host Adapters

- [ ] 10.1 定义 CLI、TUI、SDK、channel 四类 host adapter 抽象接口
- [ ] 10.2 实现最小 CLI host adapter，用于驱动 session、turn 与 ask-user 流程
- [ ] 10.3 实现最小 SDK host adapter，用于 headless prompt 与流式事件消费
- [ ] 10.4 实现 channel 风格 host adapter 的消息接入与回复接口骨架
- [ ] 10.5 将 permission prompts、ask-user、notifications 与 interrupt 统一映射到 host adapter 能力上
- [ ] 10.6 提供一个最小 end-to-end host demo，验证共享 runtime 在至少一种 interactive host 与一种 headless host 下可运行

## 11. 验证、兼容性与文档

- [ ] 11.1 增加 Claude 风格 tool 定义兼容性 fixtures 与 golden tests
- [ ] 11.2 增加 Claude 风格 agent 定义兼容性 fixtures 与 golden tests
- [ ] 11.3 增加 Claude 风格 `SKILL.md` 与 hook 定义兼容性 fixtures 与 golden tests
- [ ] 11.4 增加 routing、subagents、memory extraction、hook flow 与 built-ins 的集成测试
- [ ] 11.5 补充兼容范围说明，明确“语义兼容而非源码兼容”的边界
- [ ] 11.6 补充内置 agents、tools、skills、memory 与 hooks 的中文使用文档
