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

> 2026-05-04 复核更新：
> 本文最初用于记录 runtime 易用性缺口与演进 roadmap。当前仓库已经完成当时列出的相关 change，因此本文下面的第 3-7 节改为“复核结论”：哪些缺口已经补齐，哪些只剩下小范围收尾，而不再把这些项继续表述为当前未实现能力。

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
| Workflow-level live smoke | `demos.projects.coding_workflow_demo --live` | 同一 workflow 是否能在不引入 host/builtin replacement 的前提下切到真实 provider，并在执行前做正式 preflight | 已成立 |
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

## 3. 原始不易用点复核

下面逐条复核本文最初列出的 runtime 层不足点。结论不是“当时判断错了”，而是这些缺口现在已经大多被补齐，不应继续当作当前阻塞项。

### 3.1 官方一等 workflow test kit：已补齐

原文指出：

- deterministic workflow validation 依赖 `demos/_shared/*`
- 用户要自己复制 scripted model、temp workspace、fixture runner

当前状态：

- runtime 现在已经提供正式的 `weavert.testing` namespace
- 包含 `ScriptedModelClient`
- 包含 `copied_fixture_workspace(...)` / `temporary_workspace(...)`
- 包含 `run_workflow_test(...)`
- 包含 tool / skill / child-run assertions
- `WorkflowTestReport` 直接包裹 canonical `WorkflowRunReport`

因此，“如何测试一个 runtime workflow”已经从 demo 私有技巧变成了正式公共能力。  
`demos/_shared/scripted_model.py` 目前更多只是兼容 re-export，而不是用户必须依赖的主路径。

### 3.2 更高层 session / workflow 生命周期 helper：基本补齐

原文指出：

- headless project demo 仍要自己写 session lifecycle glue
- 普通用户不应该手工管理 `create_session -> enqueue -> stream -> close`

当前状态：

- runtime 现在提供 `run_prompt_report()`
- 也提供 `run_prompt_report_in_session()`
- 现在还提供 `stream_prompt_report()` / `stream_prompt_report_in_session()`
- `WorkflowRunReport` 已包含 terminal、final status、finalization diagnostics
- 普通 headless caller 已经不需要再自己做 terminal 收集、helper-owned close 或“边流式边拿 canonical report”的 lifecycle glue

复核结论：

- 对普通 headless workflow runner 而言，这个缺口现在已经完整补齐
- 包括 raw stream、one-shot report、helper-owned streaming report、caller-owned streaming report 这几条常见路径
- 因此它已经不再是 runtime findings 里需要继续保留的 gap

### 3.3 非交互 permission preset：已补齐

原文指出：

- headless / CI / smoke 场景缺少官方 preset
- 用户不应反复自写 allow-all stub

当前状态：

- 已有官方 `AllowAllPermissionService`
- 已有 `DenyAllPermissionService`
- 已有 `ReadOnlyPermissionService`
- 已有 `SelectiveAutoApprovePermissionService`
- 并且已支持从 preset 升级到 composed policy path

因此，这一项已经从“缺口”变成“正式控制面能力”。

### 3.4 typed 结果投影与查询 helper：已补齐

原文指出：

- `coding_workflow_demo` 需要手扫 transcript / block
- workflow 验收逻辑不应反复重写 message scanning

当前状态：

- 已有 `latest_tool_outcome(...)`
- 已有 `latest_skill_outcome(...)`
- 已有 `final_assistant_text(...)`
- 已有 `terminal_failure(...)`
- 已有 `child_summary(...)`
- 这些 helper 同时支持 raw messages 和 `WorkflowRunReport`

因此，这一项已经补齐，而且已经进入用户指南和集成指南，不再只是内部工具。

### 3.5 hook 轻量 authoring helper：已补齐

原文指出：

- 简单 hook 场景 ceremony 仍重
- 缺少 matcher shortcut 和常见 effect helper

当前状态：

- 已有 callback-oriented hook helper
- 已有 `match_tool(...)` / `match_tool_pattern(...)`
- 已有 `rewrite_input(...)` / `block_execution(...)` / `respond_to_elicitation(...)`
- helper 生成的 request 仍走同一套 validation path，而不是 helper-only bypass

因此，这一项已经从“底层协议存在但写起来偏重”改进为“简单场景已有官方轻量入口”。

### 3.6 package 轻量 builder / helper：已补齐

原文指出：

- package protocol 成立，但普通 authoring ceremony 偏重
- capability-only / context-only / provider-only pattern 应有轻量 builder

当前状态：

- 已有 `build_capability_only_package_manifest()`
- 已有 `build_context_contributor_only_package_manifest()`
- 已有 `build_provider_only_invocation_package_manifest()`
- 输出仍然是 ordinary manifest-backed package，不是第二套协议

因此，这一项也已经补齐。

### 3.7 assembly ergonomics：已补齐主干

原文指出：

- 用户需要同时理解 distribution、builtins、discovery、route、package activation
- 缺少更清晰的普通用户默认起点

当前状态：

- 已有 `RuntimeConfig.for_ordinary_workflow(...)`
- 已有 `RuntimeConfig.for_headless_live(...)`
- 已有 `RuntimeConfig.for_host_bound(...)`
- preset provenance 会发布到 runtime metadata
- 另外还补了官方 starter scaffold generation path，进一步降低 adoption 成本

因此，assembly 这条主干已经不再是“没有推荐入口”，而是“已有推荐入口，剩下是文档和示例持续收敛”。

### 3.8 live/provider preflight：已补齐

原文指出：

- live path 最好在 full run 前暴露 env / auth / route 问题
- preflight 应当是一等 runtime 能力

当前状态：

- 已有 `preflight_model_route(...)`
- 已有 `preflight_default_model_route()`
- 会返回结构化 readiness report
- starter scaffold 和 live smoke docs 已经把 preflight 作为主路径

因此，这个缺口已经补齐。

## 4. 从 runtime 层面看，当前仍值得跟踪的点

经过这轮实现后，原文列出的“缺失能力”已经大多不再成立。现在剩下更适合放在“收尾/持续优化”层面的只有少数点。

### 4.1 report-oriented streaming companion：已补齐

当前已有：

- `stream_prompt()`：原始流式 surface
- `run_prompt_report()`：report-oriented one-shot surface
- `run_prompt_report_in_session()`：caller-owned session 的 report helper
- `stream_prompt_report()`：helper-owned streaming + canonical report helper
- `stream_prompt_report_in_session()`：caller-owned streaming + canonical report helper

这意味着“边流式消费边保留 canonical run report/finalization 语义”的缺口已经关闭。  
后续如果还要继续打磨，更像是文档和 adoption path 收敛，而不是补一条新的 runtime public surface。

### 4.2 仓库内部 demo/private wrapper 仍有清理空间

仓库里仍保留少量 `demos/_shared/*` 包装层，例如：

- `run_async(...)`
- `demo_workspace(...)`
- 部分 demo 的兼容导出

这更像仓库内部清理问题，而不是 runtime 用户侧能力缺失。  
从用户视角看，公开替代 surface 已经存在，后续可以继续减少 demo-private compatibility wrapper 的存在感。

### 4.3 本文档本身不应再继续扮演“当前缺口 backlog”

因为 roadmap 中列出的大项已经基本完成，继续把本文第 3-7 节保留成“待实现清单”会误导读者。  
后续如果出现新的 runtime gap，更合适的做法是：

- 新开一份 fresh findings / review 文档
- 或直接在新的 change proposal 里记录

而不是继续沿用本文的旧 backlog 语义。

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

基于当前 demo、用户文档、公开 surface 和定向回归测试，可以得出更准确的 runtime 层结论：

- **已成立**：WeaveRT 不仅证明了 tool / agent / skill / hook / package / host 这些 seam 能跑通，还已经把 workflow testing、headless lifecycle helper、permission preset、result projection、assembly preset、preflight、starter scaffold、workflow observability 这些基础设施易用性缺口补成了正式公共能力。
- **不再成立的旧判断**：本文最初把 test kit、lifecycle helper、permission preset、result query helper、hook/package helper、assembly preset、preflight 视为当前缺失项；以 2026-05-04 的仓库状态看，这些判断已不再适合作为“当前缺口”保留。
- **当前更合理的判断**：WeaveRT 在 runtime 层最主要的工作已经从“补基本缺口”转向“持续收敛 adoption path、减少仓库内部兼容包装、按实际需求补局部增强”。

## 7. 已完成的 roadmap 回顾

本文原先在 roadmap 里列出的 runtime 基础设施项，现在已经基本都有落地对应物：

### 7.1 已完成的基础设施补齐

- 官方 workflow test kit
- 高层 headless workflow runner / report helper
- 非交互 permission presets
- live provider preflight
- typed result projection / query helpers
- hook 轻量 authoring helper
- package 轻量 builder family
- runtime assembly presets
- unified workflow observability model
- runtime starter scaffolds
- composable permission policy framework

### 7.2 下一步更适合关注什么

如果后续还要继续推进 runtime 层工作，更值得关注的是：

- 是否继续清理仓库里仍保留的 demo-private compatibility wrapper
- 是否把 adoption 文档、demo、starter scaffold 持续收敛到更少、更稳定的推荐路径

换句话说，下一阶段更像“收口与打磨”，而不是再去补当时那批显性的基础能力缺口。
