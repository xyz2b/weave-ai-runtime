# Tool / Agent / Skill 扩展规范

本文档面向要扩展这套 AI Runtime 能力图的接入方。  
目标不是讲 Runtime 内核实现细节，而是讲清楚：

- 用户如何新增 `tool`
- 用户如何新增 `agent`
- 用户如何新增 `skill`
- 哪些字段当前会真正生效
- 哪些字段只是已解析或预留，不应当作稳定依赖

如果把 `docs/weavert-integration-guide.md` 看作“Runtime 怎么接进来”，那本文就是“能力怎么接进去”。

如果你要先看可执行例子，先跑 `demos/README.md`。  
那套 demo 负责给出 repo-root 可运行的最小工作流；本文负责说明 definition authoring contract。尤其在 hook 相关字段上，当前推荐 surface 仍然是 skill hooks 和 public hook registration API，agent frontmatter 的 `hooks` 默认不应当被当作普通 v1 扩展面。

## 1. 先说结论

这套 Runtime 的核心思想是：

1. Runtime 主循环、session ingress、turn state machine、tool orchestration、memory、host bridge 由框架自己收口。
2. 用户扩展点主要落在三类 definitions 上：
   - `tool`
   - `agent`
   - `skill`
3. 用户逻辑不应该通过改主循环来接入，而应该通过 definitions 和 control-plane 接口来接入。

可以把它理解成：

```text
Runtime Core
  ├─ Session / Turn / Recovery / Memory / Host
  └─ Capability Graph
       ├─ Tools   <- 用户可扩展
       ├─ Agents  <- 用户可扩展
       └─ Skills  <- 用户可扩展
```

## 2. 目录与发现规则

Runtime 通过 `DefinitionSourcePaths` 发现 definitions。  
默认项目级目录建议如下：

```text
your-project/
└── .weavert/
    ├── tools/
    │   ├── my_tool.py
    │   └── repo_scan.py
    ├── agents/
    │   └── reviewer.md
    └── skills/
        └── review/
            └── SKILL.md
```

发现规则：

- tool
  - `tools/*.py`
- agent
  - `agents/*.md`
- skill
  - `skills/**/SKILL.md`

如果你使用：

- `RuntimeConfig.for_ordinary_workflow(project_root)`

那么 Runtime 默认会接入：

- `~/.weavert`
- `<project>/.weavert`

## 3. 命名冲突与覆盖规则

当前 registry 的优先级不是“项目覆盖内置”，而是：

```text
bundled > user > project
```

这意味着：

- 同名 bundled definition 会压过 user / project definition
- 同名 user definition 会压过 project definition
- project definition 不能仅靠同名文件覆盖 bundled definition

因此，推荐做法是：

1. 自定义能力优先使用新名字，而不是复用 bundled 同名 definition
2. 如果你在嵌入 Runtime 的 Python 装配层中确实要替换 bundled definition，应使用 `BuiltinPackConfig`
3. 如果只是项目接入方，默认不要假设 `.weavert/` 里的同名文件能覆盖 builtins

## 4. Tool 规范

### 4.1 当前最重要的一条

对“可执行的自定义工具”来说，当前唯一受支持的 file-backed authoring path 是 Python tool module。
`.weavert/tools/` 下的 `.json` / `.yaml` / `.yml` 文件现在会在 discovery 阶段被拒绝。
Python module 也必须通过 `TOOL_DEFINITION`、`TOOL` 或 `build_tool_definition()` 解析成 concrete `ToolDefinition`，且该 definition 必须提供 `execute`。

所以：

- file-backed tool 只写 `.py`
- 不要导出 `dict` / mapping-style payload
- 不要省略 `execute`

### 4.2 Python Tool 的最小写法

Python tool module 需要导出以下三种形式之一：

- `TOOL_DEFINITION`
- `TOOL`
- `build_tool_definition()`

无论使用哪种入口，最终都必须解析成 concrete `ToolDefinition`。

最小例子：

```python
from weavert.definitions import ToolDefinition, ToolTraits


async def execute(tool_input, context):
    path = context.cwd / tool_input["file_name"]
    return {
        "file_name": tool_input["file_name"],
        "exists": path.exists(),
    }


TOOL_DEFINITION = ToolDefinition(
    name="check_file",
    description="Check whether a file exists under cwd.",
    input_schema={
        "type": "object",
        "properties": {
            "file_name": {"type": "string"},
        },
        "required": ["file_name"],
        "additionalProperties": False,
    },
    traits=ToolTraits(
        read_only=True,
        concurrency_safe=True,
    ),
    execute=execute,
)
```

### 4.3 ToolDefinition 当前稳定字段

最值得依赖的字段有：

| 字段 | 作用 | 当前语义 |
| --- | --- | --- |
| `name` | canonical 名称 | 必填 |
| `description` | 能力说明 | 必填 |
| `input_schema` | 输入 schema | 用于验证和对模型暴露 |
| `output_schema` | 输出 schema | 可选；如果结果会被 typed consumer / UI / contract test 直接消费，应把它当正式结果契约显式维护 |
| `aliases` | 别名 | 可选 |
| `search_hint` | 搜索提示 | 可选 |
| `traits` | 静态特征 | 影响并发、只读、破坏性和中断行为 |
| `semantics` | 动态执行语义 | 高级用法，可覆盖 traits 推导 |
| `validate_input` | 输入校验 | 可选 |
| `check_permissions` | 工具级初始权限判断 | 可选 |
| `execute` | 执行入口 | 真正可执行工具必须提供 |

`traits` 当前最常见的 4 个字段：

- `read_only`
- `concurrency_safe`
- `destructive`
- `interrupt_behavior`

一个实用经验：

- 只读查询型工具：`read_only=True, concurrency_safe=True`
- 文件写入或有副作用的工具：保持默认或显式声明非只读

### 4.3.1 默认 OpenAI route 下的 tool schema authoring 建议

当前 bundled `openai_default` route 会把 `input_schema` 导出成 Responses strict function tools。
这不会改变 runtime 自己的 `ToolDefinition` contract，但会影响“什么 schema 最适合默认 live route”。

建议按下面的口径写：

- top-level `input_schema` 明确写成 `type: object`
- object field 尽量全部显式声明，不要依赖动态 key map
- optional field 允许保留“不在 `required` 里”的写法；adapter 会把它归一化成 `required + nullable`
  - 这是 provider-facing transport shape；provider 回传 `null` 时，bundled adapter 会在 shared tool validation / execution 前恢复成 runtime 的“字段省略”语义
- `additionalProperties: false` 是最稳妥的默认值
- 如果必须表达数组，给 `items` 写完整 schema
  - array item 内的 optional field 和 open object field 也会走同样的 strict export / round-trip restoration

这意味着自定义 tool 仍然应该把原始 `input_schema` 当作 runtime canonical contract 来写，而不是把 OpenAI transport 细节直接写进 schema。

当前 bundled OpenAI adapter 不支持 schema-valued `additionalProperties`。
如果你写的是：

```python
input_schema={
    "type": "object",
    "properties": {
        "labels": {
            "type": "object",
            "additionalProperties": {"type": "string"},
        }
    },
    "required": ["labels"],
    "additionalProperties": False,
}
```

那么 `openai_default` 会在调用前返回 `tool_schema_error`，而不是把这个动态 map 静默降级。

另外，tool trait 也会影响 live route 的实际执行体验：

- `read_only=True, concurrency_safe=True`
  - runtime 可以更积极地把它放进本地并发批次
- 写工具或有副作用的工具
  - bundled `openai_default` 现在会通过 route-level `provider_request_policy.parallel_tool_calls=true` 允许 provider-side parallel planning
  - shared coding workflow 的 continuation 顺序仍由 runtime 本地 replay 保持稳定；如果想更保守，可以在自定义 route 里显式关闭

更细的 bundled adapter 规则见 `docs/weavert-openai-responses-adapter.md`。

### 4.4 自定义用户 Tool 默认跑在 public execution path

当前非 bundled 用户工具默认不会拿到完整内部 `ToolContext`，而会跑在被收窄过的 public execution context 上。

这意味着：

- 默认拿不到 `runtime_services`
- 默认拿不到 raw `tool_pool`
- 默认拿不到 raw `private_context`
- 可以拿到只读的 `private_context_view`
- 可以拿到 catalog、session/turn state、file_state、progress、notifications、refresh handle 等公开 capability

把它想成：

```text
User Tool
   │
   └─ ToolExecutionContext
        ├─ query / session / turn metadata
        ├─ tool_catalog / agent_catalog / skill_catalog
        ├─ permission_context
        ├─ session_state / turn_state / file_state
        ├─ progress / notifications / refresh_capabilities
        ├─ memory_access
        └─ private_context_view
```

这条边界的意义是：

- 用户工具可以扩展 Runtime
- 但不应默认直接触达 Runtime 内部 service bag

### 4.5 自定义 Tool 最常用的公开能力

对大多数自定义工具来说，最常用的是这些字段：

- `context.session_id`
- `context.turn_id`
- `context.agent_name`
- `context.cwd`
- `context.messages`
- `context.tool_catalog`
- `context.agent_catalog`
- `context.skill_catalog`
- `context.permission_context`
- `context.session_state`
- `context.turn_state`
- `context.file_state`
- `context.memory_access`
- `context.refresh_capabilities`
- `context.private_context_view`

最常用的方法：

- `await context.emit_progress(...)`
- `await context.emit_notification(...)`
- `context.refresh_capabilities.request(scope, reason)`

例如：

```python
async def execute(tool_input, context):
    await context.emit_progress("repo_scan", "Scanning workspace", progress=0.1)
    receipt = context.refresh_capabilities.request("tool_pool", "unlock extra tool")
    return {
        "accepted_refresh": receipt.accepted,
        "cwd": str(context.cwd),
    }
```

### 4.6 关于执行权限的一个重要约束

当前非 bundled 用户工具不能靠自己声明 `privileged` 或 `legacy-compat` 来升级执行路由。

也就是说：

- 即使用户工具在 definition 里自声明 `runtime_execution_class="privileged"`
- Runtime 仍会把它按 public tool 处理

因此：

- 用户工具不要假设自己能直接拿到内部上下文
- 只有 Runtime 自己装配的 bundled/internal 工具才应依赖 privileged path

### 4.7 不再受支持的 file-backed Tool 写法

以下写法现在都会在 discovery 阶段被拒绝：

- `.weavert/tools/*.json`
- `.weavert/tools/*.yaml`
- `.weavert/tools/*.yml`
- 导出 `dict` / mapping-style payload 的 Python tool module
- 缺少 `execute` 的 file-backed `ToolDefinition`

## 5. Agent 规范

### 5.1 Agent 文件结构

agent 使用 `agents/*.md`。  
结构是：

- frontmatter
- prompt body

最小例子：

```md
---
name: reviewer
description: Review code changes
tools:
  - read
  - grep
permissionMode: dontAsk
maxTurns: 5
memory: project
isolation: worktree
---
You are a focused reviewer. Find regressions, unsafe edits, and missing tests.
```

### 5.2 Agent 当前真正会生效的字段

这些字段当前属于稳定且会进入执行语义的字段：

| frontmatter | 作用 | 当前语义 |
| --- | --- | --- |
| `name` | agent 名称 | 必填 |
| `description` | agent 描述 | 必填 |
| `tools` | 可用工具池 | 会参与 execution policy |
| `disallowedTools` | 显式禁止工具 | 会参与 execution policy |
| `skills` | 可用 skill 池 | 会参与 execution policy |
| `model` | 默认模型名 | 会进入 child execution / request shaping |
| `modelRoute` | 默认 route | 会参与 route 解析 |
| `effort` | 推理 effort | 会进入请求覆盖 |
| `permissionMode` | 权限模式 | 会进入 permission context |
| `maxTurns` | 最大轮数 | 会约束 child execution |
| `background` | 默认后台执行 | 会影响 spawn mode |
| `memory` | 记忆 scope | 会进入 execution policy |
| `isolation` | 执行隔离模式 | 会进入 isolation contract |

如果你在定义 worker / reviewer / verifier 这类 agent，当前主要应围绕这些字段写。

这里的 `worker` 只是角色化命名示例。当前不要自动假设 runtime 已经内置了一个同名 official bundled agent，除非相关 first-party package 明确把它装配出来。

#### 5.2.1 `maxTurns` 与运行时 `max_turns`

`maxTurns` 是 agent definition 里的静态字段，用来描述该 agent 的默认最大执行轮数。
运行时调用方也可以在 invocation 中传入 `max_turns`，把它作为本次调用的动态预算。

两者同时存在时，实际生效值取较小值：

```text
effective_max_turns = min(agent.maxTurns, invocation.max_turns)
```

这意味着运行时 `max_turns` 只能进一步收紧预算，不能突破 agent 自身定义的上限。

如果两边都没有设置，runtime 当前会使用 `8` 作为默认 fallback。

这里的 “turn” 指 agent 在一次执行中的内部迭代次数，不是用户对话消息轮次。
通常每次模型请求完成并进入下一轮恢复/推进时，都会消耗一轮 turn。

### 5.3 Agent 的推荐写法

#### 5.3.1 实现型 worker

下面这个 `worker` 例子是 authoring 示例，不代表当前 runtime 默认 bundled 同名 agent：

```md
---
name: worker
description: Handle implementation work
tools:
  - read
  - grep
  - edit
  - write
  - bash
permissionMode: acceptEdits
memory: project
isolation: worktree
---
You are a pragmatic implementation agent. Prefer the smallest correct change.
```

#### 5.3.2 审查型 verifier

```md
---
name: verifier
description: Run validation and review regressions
tools:
  - read
  - glob
  - grep
  - bash
maxTurns: 4
background: true
---
You validate changes, run checks, and summarize regressions.
```

### 5.4 Agent 中当前应视为“已解析但未完全成熟”的字段

下列字段当前会被解析进 `AgentDefinition`，但不建议把它们当成完全稳定的 authoring contract：

- `hooks`
- `initialPrompt`
- `criticalSystemReminder_EXPERIMENTAL`
- `mcpServers`

对接入方的建议是：

- 可以在定义里保留这些字段以便未来演进
- 但当前不要把它们作为关键行为前提
- 尤其不要假设 file-based agent 的 `hooks` 会像 skill hooks 一样自动注册执行
- 当前默认装配会拒绝 agent-owned hooks；只有显式 legacy compatibility mode 才会继续容忍

当前 Runtime 里真正会自动注册并执行的 definition-level hooks，主要还是 skill hooks。

## 6. Skill 规范

### 6.1 Skill 文件结构

skill 使用 `skills/<slug>/SKILL.md`。  
`slug` 默认就是 skill name。

最小例子：

```md
---
description: Review Python changes before shipping
context: fork
agent: reviewer
allowed-tools:
  - read
  - grep
paths:
  - src/**/*.py
user-invocable: false
---
# Review

Check the diff carefully and call out risky behavior changes.
```

### 6.2 Skill 当前真正会生效的字段

这些字段当前已经进入正式运行时语义：

| frontmatter | 作用 | 当前语义 |
| --- | --- | --- |
| `description` | skill 描述 | 必填或由正文推导 |
| `context` | `inline` / `fork` | 决定注入还是子执行 |
| `agent` | fork 时目标 agent | 会参与 child run |
| `allowed-tools` | 收窄工具池 | 会参与 execution policy |
| `model` | skill 级模型覆盖 | inline / fork 都会影响请求塑形 |
| `effort` | skill 级 effort 覆盖 | inline / fork 都会影响请求塑形 |
| `paths` | 路径激活范围 | 影响 invocation visibility |
| `user-invocable` | 用户可否显式调用 | 影响 host 侧调用 |
| `disable-model-invocation` | 模型可否调用 | 影响 model-visible skill pool |
| `argument-hint` | 参数提示 | 影响 invocation surface |
| `arguments` | 参数名 | 影响 invocation surface |
| `hooks` | skill hook 定义 | 会在 inline / fork 路径注册 |
| `shell` | shell block 默认 shell | 影响 prompt expansion |

### 6.3 Inline 与 Fork 的差异

skill 当前有两种主执行方式：

```text
INLINE
  -> 把 skill 展开为 injected system message
  -> 合并 request override / policy narrowing
  -> 在当前 turn 继续

FORK
  -> 派生 child agent execution
  -> 共享 runtime core
  -> 记录 child run / terminal metadata
```

适用建议：

- `inline`
  - 适合 prompt 注入、策略收窄、局部 workflow
- `fork`
  - 适合独立 worker、重型分析、需要独立 run record 的流程

### 6.4 Skill hooks 是当前最成熟的 definition-level hook

和 agent hooks 不同，skill hooks 当前已经有真正运行时语义。

#### 6.4.1 Inline skill hook

inline skill 的 hooks 会在当前 session / 当前 turn 上注册，并在 turn 结束后释放。

一个真实可用的 frontmatter 例子：

```md
---
description: Rewrite the next echo call
hooks:
  PreToolUse:
    matcher: echo
    effect:
      updated_input:
        value: rewritten
---
Rewrite the next tool use.
```

它表达的是：

- 在 `PreToolUse` 阶段
- 仅匹配 `echo`
- 把工具输入改写为指定内容

#### 6.4.2 Fork skill hook

fork skill 的 hooks 会随 child execution 一起传下去，并可观察子 agent 的停止事件，例如：

- `SubagentStop`

这使 skill 可以把“子执行生命周期观察”封装进自己的 definition。

### 6.5 Skill shell expansion 的边界

skill 支持 shell expansion，但有明确边界：

- 只支持 local file-backed skill
  - 即 `origin.source in {user, project}` 且有本地路径
- bundled skill 不能依赖 shell expansion
- shell expansion 依赖 `bash` tool 可用且未被 policy 禁止
- 执行失败会 fail closed，而不是静默跳过

当前支持两类 shell block：

#### 6.5.1 行内 `!`

```md
Before
!printf 'hello'
After
```

#### 6.5.2 fenced code block

````md
```bash
printf 'hello'
```
````

默认 shell：

- fenced block 优先按语言标签选择
- 否则用 `shell` frontmatter
- 再否则回退到 `bash`

### 6.6 Skill 的路径激活不是 UI 过滤，而是 Runtime 语义

`paths` 当前会进入 invocation catalog 解析。  
这意味着：

- skill 在当前 session 是否可见
- 用户能否调用
- 模型能否调用

都不是 host 随便决定，而是 Runtime 基于上下文做 session-scoped 解析。

更进一步：

- Runtime 还支持动态 skill roots
- 当前 session 观察到更深层路径时，更深层 `.weavert/skills/` 可以进入能力图

所以 skill authoring 最好显式考虑“路径上下文”，而不是只看文件是否存在。

## 7. 如何校验你写的 definitions 是否真的生效

新增 definitions 后，推荐至少验证 3 件事：

### 7.1 是否被发现

- registry 里是否出现
- 没有出现同名冲突或 validation error

### 7.2 是否真正可见

使用：

- `weavert.resolve_invocations(...)`
- `weavert.visible_invocations(session)`
- `weavert.invocation_diagnostics(session)`

补充判断：

- `output_schema` 不是“这个 tool 能不能跑起来”的执行前提
- 但如果你希望别的系统稳定消费这个 tool 的结果形状，它就应被当成正式 public result contract 维护
- 像 built-in `agent` tool 这种会被 schema-driven consumer 直接读取的 surface，结果字段是否声明在 `output_schema` 里，本身就是 contract 完整性的一部分

检查：

- 当前 skill 是否 visible
- 当前 skill 是否 user-invocable
- 当前 skill 是否 model-invocable
- 为什么被隐藏或被收窄

### 7.3 是否真的可执行

尤其是 tool，要确认：

- definition 不只是被发现
- 还真的带有 `execute` handler

## 8. 给扩展方的推荐工作流

```text
第一步：先用 builtins 跑通 Runtime
第二步：新增 project-level tool / agent / skill
第三步：用 invocation diagnostics 检查能力可见性
第四步：只在需要时，再在 Python 装配层用 BuiltinPackConfig 做替换或禁用
第五步：把与流程有关的逻辑尽量收进 skill hooks 或 control-plane extension，而不是改 Runtime 主循环
```

## 9. 相关文档

- `docs/weavert-integration-guide.md`
  - 讲 Runtime 怎么接进系统
- `docs/weavert-control-plane-extension-guide.md`
  - 讲 host、hook bus、permission、elicitation、sidecar 等流程接入点
- `docs/current-system-architecture.md`
  - 讲系统骨架和分层
