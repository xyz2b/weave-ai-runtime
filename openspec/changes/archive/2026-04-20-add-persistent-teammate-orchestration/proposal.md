## Why

当前 runtime 已经具备统一的 agent 执行内核，但还缺少承载 persistent teammate 的 orchestration 外层。现在更接近“共享执行器上的后台任务系统”，还没有把文件邮箱、稳定身份、权限桥接和 idle 生命周期组合成一等能力。

这个缺口已经开始影响后续 multi-agent 方向的判断：问题不在于再造一个执行器，而在于补齐执行器外面的 teammate shell，并把 task/progress 明确降级为投影与观测面。

## What Changes

- 在现有共享执行内核之上新增 persistent teammate orchestration 外层，而不是引入第二套 orchestration engine。
- 定义 file-backed mailbox contract，使用文件作为 teammate 间消息投递与读取介质，并约束并发写入与消费语义。
- 定义 teammate identity/lifecycle contract，使 teammate 以持久 worker/session 身份存在，而不是把一次 task 当作唯一身份来源。
- 定义 leader-mediated permission bridge，让 teammate 的审批与权限请求经过主控侧桥接，而不是各自直接接管宿主权限。
- 定义 idle/available lifecycle 与 task/progress projection contract，使 task、通知和进度成为对外可观测投影，而不是执行本体。
- 明确 shared execution core 继续复用现有 `AgentExecutionService` / `TurnEngine` 路径，mailbox 与 orchestration 状态不进入 turn engine 内部。

## Capabilities

### New Capabilities
- `teammate-orchestration`: 定义 persistent teammate shell，包括文件邮箱、身份建模、权限桥接、idle 生命周期，以及 task/progress 投影。

### Modified Capabilities
- None.

## Impact

- 影响 `agent` / `subagent` / `task` 相关运行时边界，以及后续 multi-agent 控制面设计。
- 依赖共享 execution core 提供统一的 child execution 路径；本 change 只补 persistent teammate orchestration shell，不重开 execution core 语义。
- 需要新增 teammate mailbox、identity registry、permission bridge、idle state 与 projection 相关模块或契约。
- 需要明确 `AgentExecutionService`、`TurnEngine`、task 系统、通知系统之间的职责边界，避免把 teammate 语义继续塞进一次性任务执行路径。
