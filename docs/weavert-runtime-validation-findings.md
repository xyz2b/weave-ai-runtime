# WeaveRT Runtime 验证结论与易用性缺口

本文档基于当前仓库中的 runnable demos，总结两类结论：

1. 这些 demo 从 **AI runtime 框架层** 已经验证了哪些能力。
2. 站在“框架使用者要做自己的产品”这个视角看，抛开用户业务自身的特殊需求后，当前 runtime 还有哪些 **不易用点** 或 **缺失能力**。

本文刻意不讨论以下内容：

- 用户自己的业务流程设计
- 用户自己的产品 UX / UI / shell
- 领域特化 prompt、tool、agent、skill
- AI coding 这类具体业务本身的流程设计

换句话说，本文只看 **runtime 是否已经把底层通用能力做好**，从而让用户把精力更多放在自己的业务能力定义上。

## 1. 范围边界

### 1.1 什么算 runtime 层能力

本文把下面这些视为 runtime 框架层能力：

- definition discovery 与 runtime assembly
- tool / agent / skill 的执行与组合
- hook 注册与生命周期注入
- package protocol attachment
- model route / provider 切换
- session / turn 生命周期管理
- permission / elicitation / host 等控制面边界
- 运行结果、错误、状态、可观测性与测试支撑

### 1.2 什么不算 runtime 层能力

下面这些不应当被算作 runtime 缺陷：

- 用户是否要做 AI coding app、客服、运营助手或别的产品
- 用户的业务工作流细节
- 用户自己的交互产品形态
- 用户自己的 tool / agent / skill 领域知识

这些本来就应该由使用框架的产品团队承担，不应要求 runtime 代替他们完成。

## 2. 当前 demo 已验证的 runtime 能力

## 2.1 分层结论

| Demo 层级 | 代表 demo | 主要验证的 runtime 能力 | 结论 |
| --- | --- | --- | --- |
| Seam basics | `demos.tools.file_backed_tool_demo`、`demos.agents.file_backed_agent_demo`、`demos.skills.file_backed_skill_demo` | `.weavert/` discovery、definition 装配、单个 tool/agent/skill 执行 | 成立 |
| Hook demos | `demos.hooks.session_register_hook_demo`、`demos.hooks.runtime_config_hook_demo`、`demos.skills.inline_skill_hook_demo` | public hook registration、skill hooks、runtime-default hooks | 成立 |
| Package demos | `demos.packages.provider_only_package_demo`、`demos.packages.general_package_demo`、`demos.packages.package_activation_demo` | manifest admission、requested activation、capability binding、context contributor、invocation provider | 成立 |
| Project demos | `demos.projects.release_workflow_demo`、`demos.projects.coding_workflow_demo` | 多个 public seams 的组合能力；ordinary extension path 是否足以完成真实 workflow | 成立 |
| Workflow-level live smoke | `demos.projects.coding_workflow_demo --live` | 同一 workflow 是否能在不引入 host/builtin replacement 的前提下切到真实 provider | 设计与 contract 已成立 |
| Advanced integration sample | `demos.apps.code_assistant` | host binding、durable state、approvals、builtin replacement、task/job integration | 成立，但属于 advanced path |

## 2.2 已经被证明成立的 runtime 能力

### A. 用户定义发现与装配已经成立

当前 demo 证明：

- 用户可以通过 `.weavert/tools/`、`.weavert/agents/`、`.weavert/skills/` 投放能力定义。
- runtime 可以在不改内核的前提下发现并装配这些定义。
- 对普通用户而言，主扩展故事已经不是“改 runtime 主循环”，而是“写自己的 tool / agent / skill”。

这直接支撑了框架的核心目标：让用户从底层 runtime 实现里抽身出来，把精力放在业务能力定义上。

### B. tool / agent / skill 的执行平面已经可组合

`coding_workflow_demo` 证明的不是单点调用，而是完整组合：

- `skill` 先约束 workflow 次序
- `grep` 做 inspect
- `edit` 做真实文件修改
- `bash` 做真实本地验证
- `review-change` skill 触发 reviewer child agent
- 最后再返回 summary

这说明 runtime 的核心执行平面已经足以支撑“小型真实 workflow”，而不是只能做 isolated examples。

### C. skill 已经是正式 workflow 抽象

当前 demo 同时验证了：

- `inline` skill：在当前 turn 内注入 workflow discipline
- `fork` skill：触发 child agent / 子流程执行
- skill hooks：skill 不只是 prompt 片段，还能携带生命周期行为

这说明 skill 在 runtime 里的定位是“可复用 workflow 封装”，而不是仅仅一段文本模板。

### D. hook 体系已经是可用的正式扩展面

从 demo 看，下面三条路径都已经真实成立：

- `session.register_hook(...)`
- `RuntimeConfig(hooks=...)`
- skill frontmatter `hooks`

也就是说，runtime 已经把“生命周期插桩”作为正式扩展能力暴露给用户，而不是要求用户 patch 主循环。

### E. package protocol 已经成立

package demo 证明了下面这些都不是概念：

- external manifest admission
- explicit activation through `requested_packages`
- package-owned capability
- package-owned context contributor
- invocation provider attachment

这表明 package boundary 已经是可用的 runtime protocol attachment，而不是仓库内部机制。

### F. workflow 与 provider 已经基本解耦

`coding_workflow_demo` 的 offline / live 双路径证明：

- 同一个 fixture
- 同一个 workflow
- 同一个 success criteria

可以只切换 model route，而不必重写 workflow 定义。

这意味着对普通用户来说，“先把 workflow 跑通，再切到真实 provider”已经是一条成立的 runtime 使用路径。

### G. Host 是正式边界，但不是普通用户必经路径

当前 demo 也清楚地证明了另一件重要的事：

- 普通 workflow 不需要 `bind_host()`
- 只有当用户要做 host-owned UX、审批、durable state、builtin replacement 时，才进入 advanced path

这非常符合通用 AI runtime 的定位：host 是正式扩展边界，但不强迫所有用户都先做 host integration。

## 3. 从 runtime 层面看，当前不易用的点

下面这些点，才是更值得算作 **runtime 层易用性问题** 的地方。

### 3.1 缺少官方一等 workflow test kit

当前 demo 的 deterministic 验证依赖很多 `demos/_shared/*` 私有 helper，例如：

- `ScriptedModelClient`
- temporary workspace helper
- allow-all permission stub
- async run / close / background-memory wait helper

这说明“如何测试一个 runtime workflow”还没有被框架本身产品化成正式能力。

对用户的影响：

- 用户虽然能写自己的 tool / agent / skill
- 但如果想给自己的 workflow 写稳定离线验收测试
- 仍然要先从 demo 里复制或改造一套测试脚手架

这不属于业务工作，而是 runtime 侧还缺少正式的测试支撑。

### 3.2 session / workflow 生命周期 helper 还不够高层

当前 project demo 里仍有不少通用 glue code 用于处理：

- create session
- enqueue prompt
- stream until idle
- collect message / terminal
- close session
- wait background memory

这些步骤本身不是用户业务逻辑，而是“如何正确使用 runtime session”的通用样板。

对用户的影响：

- 普通用户如果想写一个 headless workflow runner
- 仍然要自己处理不少 session lifecycle 细节

这说明 runtime 还缺少更高层的 workflow/session helper。

### 3.3 headless / non-host 场景下缺少现成的 permission preset

当前 demo 为了避免引入完整 host，大量直接注入了 allow-all permission service。

这暴露出一个 runtime 层问题：

- 非交互脚本场景
- CI / smoke 验证场景
- headless workflow 场景

用户常常需要的是几个现成的 permission preset，例如：

- allow-all
- deny-all
- read-only
- auto-approve selected classes

如果这些都要用户自己实现 service stub，门槛就偏高。

### 3.4 缺少更高层的运行结果投影与查询 helper

`coding_workflow_demo` 为了判断 workflow 是否成功，需要自己从 message/tool result 中提取：

- 最后一次 verification 结果
- `review-change` skill 结果
- final assistant summary
- terminal error

这说明 runtime 虽然已经有完整底层 contract，但缺少更高层的结果查询 helper。

对用户的影响：

- 用户如果想写 workflow 验收逻辑
- 很容易陷入手工扫描 `RuntimeMessage` / block 结构

这不是业务逻辑，而是 runtime 还没把常见“结果投影”做成更好用的公共能力。

### 3.5 hook authoring 对简单场景仍然偏重

现在的 hook registration model 很完整，但简单场景下 ceremony 还是比较多：

- request
- scope
- handler manifest
- contract

这套对平台化扩展是合理的，但对“只是想拦一下某个 tool 输入”的用户来说偏重。

问题不在于底层能力不够，而在于：

- 简单 use case 缺少更轻的 authoring helper
- 常见 matcher / effect 组合还没有足够顺手的封装

### 3.6 package 扩展协议成立，但 authoring ceremony 偏重

package 这套能力已经成立，但 authoring 成本比 `tool / agent / skill` 明显高很多。

对平台型用户来说这很正常；但对只想做“少量 runtime-level capability/context 注入”的用户，当前门槛仍然偏高。

真正的问题不是 package 功能缺失，而是：

- 常见模式的 authoring helper 还不够多
- package-level extension 对普通用户而言仍然偏“协议层”，不够“模板化”

### 3.7 runtime assembly 的心智成本仍然偏高

从 demo 看，用户要理解并组合：

- `RuntimeDistribution`
- `BuiltinPackConfig`
- discovery sources
- model client vs bundled live route
- package admission vs activation

这说明 runtime 的装配能力很强，但装配 ergonomics 还不够轻。

对用户的影响：

- 普通用户需要花不少精力区分“什么时候用默认 distribution”
- “什么时候需要改 builtins”
- “什么时候只需要写 definitions”

这类心智负担属于 runtime 使用门槛，不是业务层问题。

### 3.8 live/provider 侧 preflight 还不够一等

现在 workflow-level live smoke 已经有清晰的 credential failure contract，这是好的。

但从用户体验看，runtime 仍然更适合提供更正式的 preflight 能力，例如：

- route readiness check
- required env check
- provider capability summary
- clear structured failure before a full run starts

这样用户切到 live path 时，不用依赖完整 workflow 执行后再理解失败原因。

## 4. 从 runtime 层面看，当前更像“缺失能力”的点

如果把上面的“不易用点”再往前推一步，可以抽象成几类更明确的 runtime 缺失能力。

### 4.1 官方 workflow test kit

建议 runtime 层提供正式公共能力，例如：

- scripted / fake model route
- workflow fixture runner
- temp workspace helper
- standardized run report
- assertion helpers for tool / skill / child-run outcomes

### 4.2 更高层的 headless workflow runner

建议 runtime 层提供比“手工 create_session + stream + close”更高层的 helper，例如：

- run-workflow helper
- prompt + stream + finalize helper
- session report helper

### 4.3 内置 permission presets

建议 runtime 层提供正式的非交互 preset，而不是让用户反复写自己的 stub service。

### 4.4 typed result projection / query helper

建议 runtime 层补强这类能力：

- latest tool result lookup
- skill outcome lookup
- child run summary lookup
- terminal failure projection
- run report query helper

### 4.5 hook/package 的轻量 authoring helper

建议保留当前底层协议，但为常见模式补一层轻量 helper，降低用户 authoring ceremony。

### 4.6 更明确的 assembly preset / preflight

建议 runtime 层提供更清楚的：

- common assembly presets
- provider readiness / env preflight
- ordinary-user recommended defaults

## 5. 哪些点不应继续往 runtime 里放

为了避免 scope 漂移，这里也明确列出不建议塞回 runtime 的内容：

- AI coding 业务 workflow 本身
- 用户自己的产品 shell / Web UI / IDE UX
- 领域特化 reviewer / planner / verifier prompt
- 用户自己的业务 tool / agent / skill 语义
- 具体产品里的 workflow ledger、任务面板、业务审批规则

这些都属于“用户使用 runtime 做产品时应该自己开发的业务层内容”。

runtime 更应该承担的是：

- 底层运行与编排
- 正式扩展边界
- 测试与可观测支撑
- provider / session / permission / hook / package 的通用能力

## 6. 综合判断

基于当前 demo，可以得出下面这个更聚焦的 runtime 层结论：

- **已成立**：WeaveRT 已经证明，用户可以主要通过自己的 `tool / agent / skill` 定义，把精力从底层 runtime 主循环实现中解放出来。
- **仍偏重**：用户一旦要做 workflow 验证、headless 控制、hook/package authoring、结果抽取、live preflight，仍会碰到不少 runtime 侧的 glue code 与 ceremony。
- **最值得优先补的不是业务能力，而是 runtime 基础设施易用性**：测试 kit、lifecycle helper、permission preset、结果查询 helper、轻量 authoring helper、assembly/preflight。

## 7. Runtime 演进 roadmap

下面这份 roadmap 只针对 runtime 层通用能力，不包含业务层工作流或产品层交互形态。

优先级判断标准是：

- 是否能减少用户必须自己写的 runtime glue code
- 是否是普通框架使用者的高频需求
- 是否能提升 workflow 验证、装配和 live 切换的体验
- 是否不会把业务层职责重新塞回 runtime

### 7.1 短期

这些项目最值得优先做，因为它们能最快降低普通用户的使用门槛。

#### A. 官方 workflow test kit

目标：

- 让用户不必再从 `demos/_shared/*` 复制测试脚手架

建议内容：

- scripted / fake model route
- temp workspace helper
- standard workflow test runner
- assertion helpers for tool / skill / child-run outcomes

优先理由：

- 这是当前最明显的 runtime 使用缺口
- 能直接把“demo 私有能力”变成“框架正式能力”

#### B. 更高层的 headless workflow runner

目标：

- 让用户不必反复手写 `create_session -> enqueue -> stream -> close`

建议内容：

- `run_workflow(...)`
- `stream_workflow(...)`
- `run_prompt_with_report(...)`

优先理由：

- 这部分是最常见的 runtime lifecycle glue
- 做完后，普通用户更容易专注在自己的 tool / agent / skill 上

#### C. 非交互 permission presets

目标：

- 让 headless / CI / smoke 场景不再依赖用户自己写 permission stub

建议内容：

- allow-all preset
- deny-all preset
- read-only preset
- auto-approve selected classes preset

优先理由：

- 这是 runtime 控制面的通用需求
- 明显属于框架层，而不是业务层

#### D. live provider preflight

目标：

- 让用户在切到 live path 前，更早知道 env / auth / route 是否就绪

建议内容：

- required env check
- route readiness check
- structured preflight report

优先理由：

- 用户感知强
- 实现边界清楚
- 能直接改善 workflow-level live smoke 体验

### 7.2 中期

这些项目的底层能力已经存在，但 authoring 或使用 ergonomics 仍然偏重。

#### A. typed result projection / query helpers

目标：

- 让用户不必手扫 `RuntimeMessage` / block 结构来提取 workflow 结果

建议内容：

- latest tool result lookup
- latest skill outcome lookup
- child run summary lookup
- terminal failure projection
- run report query helper

放在中期的原因：

- 很重要，但最好建立在高层 workflow runner 先稳定之后

#### B. hook 轻量 authoring helper

目标：

- 让简单 hook 场景不必写完整 ceremony

建议内容：

- matcher shortcuts
- common effect helpers
- callback-oriented helper constructors

放在中期的原因：

- 现有 hook contract 已经完整
- 当前主要缺的是易用性，而不是功能

#### C. package 轻量 builder / helper

目标：

- 降低 capability-only / context-only / provider-only 这类常见 package pattern 的 authoring 成本

建议内容：

- capability package builder
- context-contributor package builder
- provider-only builder 扩展

放在中期的原因：

- package 是偏高级扩展面
- 先做 helper 比重做协议更划算

#### D. runtime assembly presets

目标：

- 降低用户在 distribution / builtins / route / discovery 上的装配心智负担

建议内容：

- ordinary workflow preset
- headless live preset
- host-bound preset

放在中期的原因：

- 需要建立在 workflow runner、permission preset、test kit 等前面能力相对稳定之后

### 7.3 长期

这些项目更偏体系化收敛，适合在前面基础能力打稳后再做。

#### A. 统一的 workflow observability model

目标：

- 统一 headless run、host run、child run、tool run 的状态表达与投影方式

建议内容：

- unified run report
- unified event projection
- structured workflow diagnostics

放在长期的原因：

- 会涉及多条现有 query / event / report contract 的收敛

#### B. composable permission policy framework

目标：

- 从简单 preset 进一步演进到可组合、可声明的 permission policy

建议内容：

- scope-based rules
- tool/risk class policy
- policy composition

放在长期的原因：

- 比 preset 更强，但也更容易复杂化
- 应建立在普通 preset 路径先被充分验证之后

#### C. runtime starter scaffold

目标：

- 降低用户起一个“最小 runtime 项目”的 adoption 成本

建议内容：

- minimal project scaffold
- headless workflow scaffold
- live smoke scaffold

放在长期的原因：

- 它更像 adoption accelerator
- 适合等前面的 runtime 基础能力稳定后再固化模板

### 7.4 推荐优先级

如果只选最先做的 5 件事，本文件建议顺序是：

1. workflow test kit
2. 高层 session/workflow lifecycle helper
3. headless permission presets
4. live provider preflight
5. typed result projection / query helper

这 5 项完成后，普通框架使用者在 runtime 层面会明显更少碰到：

- 测试脚手架重复建设
- session lifecycle glue code
- headless permission stub
- live smoke 前置检查不足
- 结果提取过于底层
