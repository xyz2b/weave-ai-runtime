# Tool / Agent / Skill 扩展规范

本文档面向要扩展这套 AI Runtime 能力图的接入方。  
目标不是讲 Runtime 内核实现细节，而是讲清楚：

- 用户如何新增 `tool`
- 用户如何新增 `agent`
- 用户如何新增 `skill`
- 哪些字段当前会真正生效
- 哪些字段只是已解析或预留，不应当作稳定依赖

如果把 `docs/runtime-integration-guide.md` 看作“Runtime 怎么接进来”，那本文就是“能力怎么接进去”。

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
└── .runtime/
    ├── tools/
    │   ├── my_tool.py
    │   └── my_tool.yaml
    ├── agents/
    │   └── reviewer.md
    └── skills/
        └── review/
            └── SKILL.md
```

发现规则：

- tool
  - `tools/*.{json,yaml,yml,py}`
- agent
  - `agents/*.md`
- skill
  - `skills/**/SKILL.md`

如果你使用：

- `RuntimeConfig.for_project(project_root)`

那么 Runtime 默认会接入：

- `~/.runtime`
- `<project>/.runtime`

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
3. 如果只是项目接入方，默认不要假设 `.runtime/` 里的同名文件能覆盖 builtins

## 4. Tool 规范

### 4.1 当前最重要的一条

对“可执行的自定义工具”来说，当前主路径应当使用 Python tool module。  
虽然 `json/yaml` 也能被发现为 `ToolDefinition`，但如果 definition 没有 `execute` handler，Runtime 执行时会返回：

```text
Tool '<name>' has no execution handler
```

所以：

- `py` 适合可执行用户工具
- `json/yaml` 更适合静态描述、占位定义、或未来外部执行器接入的 metadata carrier

### 4.2 Python Tool 的最小写法

Python tool module 需要导出以下三种形式之一：

- `TOOL_DEFINITION`
- `TOOL`
- `build_tool_definition()`

最小例子：

```python
from runtime.definitions import ToolDefinition, ToolTraits


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
| `output_schema` | 输出 schema | 可选 |
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

### 4.7 YAML / JSON Tool 的建议边界

如果你写的是 `yaml/json` tool definition，当前建议只把它当作：

- 静态能力描述
- schema 描述
- catalog 暴露元数据

不要把它当成“已经具备执行逻辑的用户工具”。

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
- 当前 session 观察到更深层路径时，更深层 `.runtime/skills/` 可以进入能力图

所以 skill authoring 最好显式考虑“路径上下文”，而不是只看文件是否存在。

## 7. 如何校验你写的 definitions 是否真的生效

新增 definitions 后，推荐至少验证 3 件事：

### 7.1 是否被发现

- registry 里是否出现
- 没有出现同名冲突或 validation error

### 7.2 是否真正可见

使用：

- `runtime.resolve_invocations(...)`
- `runtime.visible_invocations(session)`
- `runtime.invocation_diagnostics(session)`

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

- `docs/runtime-integration-guide.md`
  - 讲 Runtime 怎么接进系统
- `docs/runtime-control-plane-extension-guide.md`
  - 讲 host、hook bus、permission、elicitation、sidecar 等流程接入点
- `docs/current-system-architecture.md`
  - 讲系统骨架和分层
