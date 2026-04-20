## Context

当前 runtime 已经有共享执行内核：child work 最终都可以落到统一的 agent execution 路径，并继续复用同一套 turn 执行能力。现有缺口不在执行器本身，而在执行器外面还没有 persistent teammate orchestration 外层。

这层外壳当前至少缺四类能力：文件邮箱、稳定 teammate 身份、主控侧权限桥接、idle/available 生命周期。结果是系统更像“后台任务 + 通知”，而不是“持久 teammate + mailbox + 投影任务”。

本设计还需要同时覆盖两种承载方式：
- out-of-process teammate：天然更接近 session/worker
- in-process teammate：虽然运行时会被 task 承载，但本体仍然应该是 actor-like teammate，而不是 task 本身

约束条件：
- 不引入第二套执行引擎
- 不把 mailbox 状态塞进 `TurnEngine`
- 不把一次性 `agent` 调用直接拉伸成完整 teammate 语义

与 `add-agent-execution-control-plane` 的边界：
- execution-control-plane 负责 `AgentExecutionService`、execution spec、shared turn path、policy trimming 与 child run record 等共享执行内核能力。
- 本 change 负责 persistent teammate shell，包括 mailbox、identity registry、permission bridge、idle lifecycle 与 task/progress projection。
- 实现顺序上可以先后错位，但职责边界不能错位：teammate shell 可以暂时适配当前 child execution path，最终仍必须收敛回统一 execution service。

## Goals / Non-Goals

**Goals:**
- 在共享执行内核之上定义 persistent teammate orchestration shell
- 选择 file-backed mailbox 作为 teammate 间消息载体
- 建立 teammate 的持久身份与生命周期模型
- 将权限请求收敛到主控侧 permission bridge
- 明确 task、progress、notification 只是对 teammate 状态的投影

**Non-Goals:**
- 本 change 不实现新的独立 swarm executor
- 本 change 不改写 `TurnEngine` 的核心职责
- 本 change 不要求一次性完成所有 UI 或 host 集成细节
- 本 change 不把普通一次性 child agent 自动升级成持久 teammate

## Decisions

### 1. 在共享执行内核上方增加 teammate shell

新增 teammate orchestration 外层，负责 mailbox、identity、permission bridge、idle lifecycle 与 projection state。真正执行某个 mailbox item 时，外层只负责把工作项转换成结构化 execution request，然后继续调用现有共享执行内核。

这样做的原因是当前系统的执行基座已经足够统一，重复引入第二套 orchestration engine 只会让 policy、transcript、host bridge 和 observability 再次分叉。

Alternatives considered:
- 单独新增 multi-agent executor。拒绝，因为会复制已有 execution/policy/observability 逻辑。
- 继续把 teammate 语义堆在一次性 `agent` 调用上。拒绝，因为无法稳定表达 mailbox、idle 与 persistent identity。

### 2. mailbox 采用文件实现

mailbox 采用文件系统作为持久载体。每个 teammate 拥有独立 inbox，消息以离散 envelope 文件持久化；写入端通过临时文件加原子 rename 发布消息；消费端通过 claim/lock 机制避免并发冲突。消息体只保存 envelope 与必要元数据，大对象或工作区内容继续使用文件路径引用。

选择文件而不是内存队列或独立服务，主要是为了保留进程外可见性、重启恢复能力，以及较低的集成成本。这个方案也更适合当前阶段的本地 runtime 形态。

ADR 摘要：
- Decision: mailbox v1 使用本地文件系统承载 message envelope 与 teammate lifecycle snapshot
- Status: accepted
- Consequence: 获得跨进程可见性、重启恢复与低基础设施成本，但需要自行承担 claim、lease、recovery 与目录清理语义
- Rejected alternatives: 纯内存队列、外置数据库/队列服务

v1 mailbox 文件契约：

```text
<mailbox_root>/
  teams/<team_id>/teammates/<teammate_id>/
    inbox/
    claimed/
    done/
    failed/
    retry/
    state.json
```

- `inbox/`：已发布、待消费的 envelope，文件名使用稳定 `message_id`
- `claimed/`：已被某个 consumer 独占领取的 envelope，文件名附带 `claim_id`
- `done/`：成功完成的 envelope 归档
- `failed/`：达到终止条件、不再自动重试的 envelope 归档
- `retry/`：需要重新入队的 envelope 归档或中转区
- `state.json`：teammate 最新 lifecycle snapshot，包括 `teammate_id`、`state`、`current_run_id`、`current_message_id`、`waiting_permission_id`

v1 envelope 最小字段：
- `message_id`
- `team_id`
- `teammate_id`
- `kind`
- `sender`
- `created_at`
- `attempt`
- `correlation_id`
- `payload`
- `payload_ref`

发布与消费规则：
- writer 先写临时文件，再以原子 rename 发布到 `inbox/`
- consumer 通过同文件系统内的原子 move/rename 将 envelope 迁移到 `claimed/`
- 执行结束后，envelope 必须进入 `done/`、`failed/` 或 `retry/` 之一，避免停留在无终态的中间目录
- `payload_ref` 优先用于大文本、工作区路径或需要延迟加载的上下文，避免把 mailbox 变成大对象存储

Alternatives considered:
- 内存队列。拒绝，因为重启丢失、跨进程不可见。
- 外置数据库或队列服务。拒绝，因为当前文档阶段不需要先引入新的基础设施。

### 3. teammate 身份以 worker/session 为主，task 只是投影

teammate 需要稳定的 `teammate_id`，并持有独立于单次执行的生命周期。单次 mailbox 消费产生 `run_id`，面向宿主或 UI 的 task/progress 只是对当前 run 的投影，而不是 teammate 的本体。

这也适用于 in-process teammate：即使它被某个 task 承载，其真实身份仍然是持久 teammate；task 只是当前执行槽位的宿主化表示。out-of-process teammate 则更直接地体现为持久 worker/session。

Alternatives considered:
- 用 `task_id` 作为 teammate 主身份。拒绝，因为 task 关闭后身份就消失，无法表达 idle teammate 的持续存在。
- 用 run record 直接替代 teammate registry。拒绝，因为 run 是瞬时执行记录，不适合作为可寻址 actor 身份。

### 4. 权限桥接由主控侧统一处理

teammate 不直接拥有宿主权限入口。任何审批、权限升级或需要人工确认的动作都先进入 permission bridge，由主控侧统一转发到宿主审批面，再将结果回传给对应 teammate。

这样做可以保证权限模型仍然以主控 session 为中心，避免多个 teammate 分别与宿主建立并行权限通道，导致策略收敛和审计面失真。

Alternatives considered:
- 允许 teammate 直接向宿主请求权限。拒绝，因为会破坏统一的权限边界和审计路径。

### 5. idle/available 生命周期与 task 生命周期分离

teammate 需要独立的生命周期状态，至少包括 `starting`、`idle`、`active`、`waiting_permission`、`stopping`、`stopped`。task/progress/notification 从这些状态派生，而不是反过来驱动 teammate 是否存在。

当 teammate 完成当前 mailbox item 且 inbox 为空时，它回到 `idle`；后续新消息到达时可以再次激活，而不需要重新定义一个全新 teammate 身份。

Alternatives considered:
- 仅保留 task 状态机。拒绝，因为 task 关闭后无法表达 teammate 仍然在线且可继续接单。

v1 lifecycle 状态表：

| State | 含义 | 典型进入条件 | 典型退出条件 | 对外投影 |
| --- | --- | --- | --- | --- |
| `starting` | teammate 已注册，正在恢复 mailbox 或建立执行上下文 | spawn / restore | `idle` / `stopped` | 可选的初始化通知，不要求暴露长期 task |
| `idle` | 可寻址但当前无正在处理的 work item | 启动完成、队列清空 | `active` / `stopping` | 可选 idle 指示；默认不需要活跃 task |
| `active` | 正在处理某个 claimed work item | 成功 claim envelope | `idle` / `waiting_permission` / `stopping` | 活跃 task + progress |
| `waiting_permission` | 因权限审批暂停 | active run 发出 permission request | `active` / `stopping` / `idle` | blocked task + approval notification |
| `stopping` | 已收到停止请求，正在收尾或驱逐 | explicit stop / shutdown | `stopped` | stopping task 或终止通知 |
| `stopped` | 不再可寻址 | 停止完成 | 无 | 关闭 task，保留必要终态记录 |

状态迁移规则：
- `idle -> active` 只能由成功 claim mailbox item 触发
- `active -> waiting_permission` 只能由 permission bridge 挂起触发
- `waiting_permission -> active` 由批准后恢复触发，`waiting_permission -> idle` 由拒绝或取消当前 work item 触发
- `active -> idle` 仅在当前 envelope 已进入终态目录且 inbox 暂空时成立

### 6. failure / recovery 先保证 correctness

v1 不追求复杂恢复，而优先保证 mailbox 不丢件、不重复消费、状态可解释。

恢复规则：
- runtime 启动时必须扫描 `claimed/` 与 `state.json`
- 若某个 claimed envelope 对应的 consumer 已失活，且没有匹配的活跃 run record 或 permission wait 记录，则该 envelope 必须转入 `retry/` 或重新发布回 `inbox/`
- 若 `state.json` 标记为 `waiting_permission`，runtime 必须恢复对应的等待态，并继续持有 `waiting_permission_id`，直到 bridge 返回终态或超时清理
- 若 envelope 已处于 `done/`、`failed/` 或 `retry/`，恢复流程不得再次把它当作未消费消息处理

stale claim 判定：
- `claim_id` 必须绑定 `claimed_at` 与 `claimer_identity`
- 当 claim 超过租约时间且 claimer 无心跳或无活动 run linkage 时，该 claim 视为 stale
- stale claim 进入恢复流程前，runtime 必须先清理 task/progress projection，避免宿主继续看到幽灵中的 active task

这套规则故意把“能否无缝恢复正在进行中的模型调用”排除在 v1 外。跨进程重启后，进行中的执行默认转化为 retry 或失败回收，而不是伪装成可透明续跑。

### 7. appendix: v1 operational knobs

这一节只固定语义，不固定实现默认值。具体时长、次数与保留期可以由 runtime 或 host policy 注入，但字段含义必须稳定。

claim / lease 相关：

| 字段 | 语义 | 说明 |
| --- | --- | --- |
| `claim_id` | 本次独占领取的标识 | 每次重新 claim 都必须变化，不能复用旧值 |
| `claimed_at` | claim 建立时间 | 用于 stale claim 判定 |
| `claim_lease_ms` | claim 租约时长 | 超时后允许进入 stale 检测，但不等同于立即重领 |
| `last_heartbeat_at` | 最近一次 consumer 心跳时间 | 用于区分“长任务仍存活”与“consumer 已失活” |
| `claimer_identity` | 当前 claimer 身份 | 至少可区分进程或 worker 实例 |

retry 相关：

| 字段 | 语义 | 说明 |
| --- | --- | --- |
| `attempt` | 当前 envelope 已尝试次数 | claim 后执行失败或恢复重入时递增 |
| `retry_max_attempts` | 最大自动重试次数 | 超限后必须转入 `failed/`，不能无限回流 |
| `retry_reason` | 最近一次重试原因 | 例如 stale claim、host shutdown、transient execution failure |
| `next_retry_after` | 下次允许重试的最早时间 | 用于最小 backoff 语义；v1 不要求复杂调度器 |

`state.json` 保留字段：

| 字段 | 必填 | 语义 |
| --- | --- | --- |
| `schema_version` | 是 | state snapshot 版本号 |
| `team_id` | 是 | 所属 team |
| `teammate_id` | 是 | 持久 teammate 身份 |
| `state` | 是 | 当前 lifecycle state |
| `current_message_id` | 否 | 当前正在处理或等待恢复的 envelope |
| `current_run_id` | 否 | 当前 run linkage |
| `current_claim_id` | 否 | 当前 claim linkage |
| `waiting_permission_id` | 否 | 正在等待的权限请求标识 |
| `updated_at` | 是 | 最新状态写入时间 |

约束：
- `state.json` 是 lifecycle snapshot，不是审计日志；历史变更应由 run record、mailbox terminal files 或其他 observability surface 承担
- `current_message_id`、`current_run_id`、`current_claim_id` 必须保持一致性，不能跨不同 envelope 混拼
- 当 teammate 进入 `idle` 或 `stopped` 时，当前 work item 相关字段必须清空或显式置空，避免恢复流程误判
- `retry_max_attempts` 的决策点必须发生在 envelope 重新入队前，而不是下一次 claim 后才补判
- `claim_lease_ms` 超时只代表“可疑”，最终进入 stale recovery 仍必须结合心跳、run linkage 与 permission wait 状态判定

最小 JSON 示例：

mailbox envelope:

```json
{
  "schema_version": 1,
  "message_id": "msg_01JXYZ...",
  "team_id": "team_alpha",
  "teammate_id": "tm_researcher",
  "kind": "work_item",
  "sender": {
    "type": "leader",
    "id": "main"
  },
  "created_at": "2026-04-19T09:00:00Z",
  "attempt": 1,
  "correlation_id": "corr_01JXYZ...",
  "payload": {
    "instruction": "Investigate mailbox recovery behavior"
  },
  "payload_ref": null
}
```

claimed `state.json`:

```json
{
  "schema_version": 1,
  "team_id": "team_alpha",
  "teammate_id": "tm_researcher",
  "state": "active",
  "current_message_id": "msg_01JXYZ...",
  "current_run_id": "run_01JXYZ...",
  "current_claim_id": "claim_01JXYZ...",
  "waiting_permission_id": null,
  "updated_at": "2026-04-19T09:00:03Z"
}
```

waiting permission `state.json`:

```json
{
  "schema_version": 1,
  "team_id": "team_alpha",
  "teammate_id": "tm_researcher",
  "state": "waiting_permission",
  "current_message_id": "msg_01JXYZ...",
  "current_run_id": "run_01JXYZ...",
  "current_claim_id": "claim_01JXYZ...",
  "waiting_permission_id": "perm_01JXYZ...",
  "updated_at": "2026-04-19T09:00:08Z"
}
```

## Glossary

- `teammate`：可持久寻址的 worker/actor，本身不是一次性 task。
- `teammate_id`：teammate 的稳定身份标识，跨多个 work items 保持不变。
- `message_id`：mailbox envelope 的稳定标识，用于发布、claim、归档与幂等判断。
- `run_id`：某次具体执行的标识，通常在 claim 后生成，可随每次 work item 变化。
- `task`：面向宿主或 UI 的执行投影，不是 teammate 的本体身份。
- `projection`：由 teammate lifecycle 和 current run 派生出的 task、progress、notification 视图。

## Risks / Trade-offs

- `[文件邮箱并发复杂度]` 多写者/多读者下容易出现重复消费或乱序。 → Mitigation：使用原子发布、claim/lock 以及显式状态文件，先保证正确性再讨论吞吐。
- `[身份模型变重]` 新增 teammate registry 与 lifecycle 可能提高控制面复杂度。 → Mitigation：保持 teammate shell 只管理 orchestration 元数据，执行细节继续留在共享执行内核。
- `[in-process 与 out-of-process 语义漂移]` 两种承载方式可能各自演化。 → Mitigation：统一 `teammate_id`、mailbox、permission bridge 与 lifecycle contract。
- `[投影状态不一致]` task/progress 可能与真实 teammate 状态脱节。 → Mitigation：由单一 projection builder 从 teammate state 和 current run 生成宿主可见状态。

## Migration Plan

1. 先定义 teammate shell 的文档契约，包括 mailbox、identity、permission bridge、lifecycle 与 projection 规则。
2. 增加 file-backed mailbox 与 teammate registry，但先继续复用现有共享执行内核。
3. 将 permission bridge 和 idle lifecycle 接入宿主可见的 task/notification 投影。
4. 再把未来 multi-agent 流程逐步迁入 teammate shell，而不是直接扩展一次性 `agent` 路径。

回滚策略：
- 如果 shell 引入后出现稳定性问题，可禁用 teammate shell，只保留现有直接 child execution 路径。

## Open Questions

- mailbox 根目录最终应挂在 team/session 维度，还是 runtime 全局维度再做命名隔离。
- 单个 teammate 在 v1 是否只允许串行消费 mailbox，还是要保留受控并发槽位。
- mailbox envelope、run record 与 idle state 的保留时长由 runtime 还是宿主策略决定。
