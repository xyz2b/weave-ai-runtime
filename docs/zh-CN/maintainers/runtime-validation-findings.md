# WeaveRT Runtime 验证回顾

> 文档说明：这个文件仍然是面向维护者的深度回顾。索引入口请从 `docs/zh-CN/maintainers/validation-findings.md` 开始。
> 字段名、类型名和公开 helper 名称保持英文写法，避免与代码实际符号脱节。

这个维护者参考文档保留较长的 runtime 回顾：哪些 runnable demos 已经验证了 runtime 能力，历史上暴露过哪些 adoption 或 usability gaps，以及这些 gaps 里哪些现在已经关闭。

主阅读路径：

- Examples index -> `examples/README.zh-CN.md`
- Docs home -> `docs/zh-CN/README.md`
- Maintainer validation index -> `docs/zh-CN/maintainers/validation-findings.md`

当你已经知道主阅读路径，只想看一份长篇回顾时，再使用这页。
它并不尝试覆盖用户自己的业务 workflow 设计、产品 UX/UI、领域定义，或某个应用自身的产品策略。

> 2026-05-04 回顾更新：
> 这个文件最初用于跟踪 runtime 可用性缺口与路线图 follow-up。相关改动现在已完成，因此 3-7 节应被理解为回顾结论，而不是当前仍然缺失的能力。

## 1. 范围

### 1.1 什么算 runtime-layer capability

本文件把下列内容视为 runtime-framework capability：

- definition discovery 与 runtime assembly
- tool / agent / skill 的执行与组合
- hook registration 与 lifecycle injection
- package protocol attachment
- model route / provider switching
- session / turn 生命周期管理
- permission、elicitation 与 host integration 这类 control-plane boundaries
- outputs、errors、state、observability 与 testing support

### 1.2 什么不算 runtime-layer gap

以下内容不应被视为 runtime 缺陷：

- 用户要做 AI coding app、support assistant、operations assistant 还是别的产品
- 属于产品团队的业务 workflow 细节
- 由采纳者选择的交互壳层或产品形态
- 采纳者自己 tool / agent / skill 层里的领域知识

## 2. 当前 demos 已经验证的 runtime 能力

### 2.1 分层结论

| Demo layer | Representative demos | 主要验证的 runtime capability | 结论 |
| --- | --- | --- | --- |
| Seam basics | `examples.tools.file_backed_tool_demo`、`examples.agents.file_backed_agent_demo`、`examples.skills.file_backed_skill_demo` | `.weavert/` 发现、definition assembly、单个 tool/agent/skill 执行 | 已验证 |
| Hook demos | `examples.hooks.session_register_hook_demo`、`examples.hooks.runtime_config_hook_demo`、`examples.skills.inline_skill_hook_demo` | 公开 hook registration、skill hooks、runtime-default hooks | 已验证 |
| Package demos | `examples.packages.provider_only_package_demo`、`examples.packages.general_package_demo`、`examples.packages.package_activation_demo` | manifest admission、requested activation、capability binding、context contributors、invocation providers | 已验证 |
| Project demos | `examples.projects.release_workflow_demo`、`examples.projects.coding_workflow_demo` | 多个公开 seams 的组合，以及普通扩展路径是否足够支撑真实 workflow | 已验证 |
| Workflow-level live smoke | `examples.projects.coding_workflow_demo --live` | 同一 workflow 在真实 provider 上运行，且保留 preflight | 已通过 live run 验证 |
| Advanced integration sample | `examples.apps.code_assistant` | host binding、durable state、approvals、builtin replacement、task/job integration | 已验证，但属于高级路径 |

### 2.2 已被实践证明的能力

- A. 用户定义发现与组装已建立：`.weavert/tools/`、`.weavert/agents/`、`.weavert/skills/` 已经是普通用户主要扩展故事。
- B. Tool / agent / skill 执行面能干净组合：`coding_workflow_demo` 已证明 inspect -> edit -> verify -> review 的真实闭环。
- C. Skills 已是一等工作流抽象：`inline`、`fork` 与 skill hooks 都已有稳定用法。
- D. Hook 系统已是可用的公开扩展面：`session.hooks...`、`RuntimeConfig(hooks=...)` 与 skill frontmatter `hooks` 都有运行证明。
- E. Package protocol 已建立：外部 manifests、显式 activation、capability、context contributor 与 invocation provider 都已是实际协议，而不是概念设计。
- F. Workflow 与 provider 基本解耦：同一 workflow、同一 fixture、同一成功标准可以只切换 model route。
- G. Host 是真实边界，但不是每个用户的必经路径：普通 workflows 不需要 `bind_host()`，高级路径只在用户确实需要 host-owned UX、durable state 或 builtin replacement 时出现。

## 3. 对原始可用性缺口的回顾

### 3.1 Official workflow test kit：已关闭

- `weavert_testing` 已成为正式命名空间
- 提供 `ScriptedModelClient`
- 提供 `copied_fixture_workspace(...)` / `temporary_workspace(...)`
- 提供 `run_workflow_test(...)`
- 提供 tool / skill / child-run assertions

### 3.2 更高层 session / workflow lifecycle helpers：基本关闭

- 现在已有 `run_prompt_report()`、`run_prompt_report_in_session()`
- 也有 `stream_prompt_report()` / `stream_prompt_report_in_session()`
- host-bound 路径也有 `bound.run_prompt_report()` / `bound.run_prompt_report_in_session()`

### 3.3 非交互 permission presets：已关闭

- `AllowAllPermissionService`
- `DenyAllPermissionService`
- `ReadOnlyPermissionService`
- `SelectiveAutoApprovePermissionService`

### 3.4 类型化结果投影与查询 helpers：已关闭

- `latest_tool_outcome(...)`
- `latest_skill_outcome(...)`
- `final_assistant_text(...)`
- `terminal_failure(...)`
- `child_summary(...)`

### 3.5 轻量 hook 编写 helpers：已关闭

- `match_tool(...)` / `match_tool_pattern(...)`
- `rewrite_input(...)` / `block_execution(...)` / `respond_to_elicitation(...)`

### 3.6 轻量 package builders / helpers：已关闭

- `build_capability_only_package_manifest()`
- `build_context_contributor_only_package_manifest()`
- `build_provider_only_invocation_package_manifest()`

### 3.7 Assembly ergonomics：主线已关闭

- `RuntimeConfig.for_ordinary_workflow(...)`
- `RuntimeConfig.for_headless_live(...)`
- `RuntimeConfig.for_host_bound(...)`
- preset provenance 已写入 runtime metadata
- 官方 starter-scaffold generation path 已就位

### 3.8 Live/provider preflight：已关闭

- `preflight_model_route(...)`
- `preflight_default_model_route()`
- 都返回结构化 readiness reports

## 4. 仍值得追踪的 runtime-level 事项

### 4.1 Report-oriented streaming companion：已关闭

当前已形成完整族：

- `stream_prompt()`
- `run_prompt_report()`
- `run_prompt_report_in_session()`
- `stream_prompt_report()`
- `stream_prompt_report_in_session()`

### 4.2 内部 demo/private wrappers 仍有清理空间

- `run_async(...)`
- `demo_workspace(...)`
- 某些 demo 的 compatibility exports

### 4.3 本文件不应再充当当前缺口 backlog

后续新缺口更适合：

- 另起新的 findings/review 文档
- 或直接写进新的 change proposal

## 5. 什么不应该被推回 runtime

- AI coding 的业务 workflow 本身
- 用户的产品 shell、web UI 或 IDE UX
- 领域特定的 reviewer / planner / verifier prompts
- 用户自己的业务特定 tool / agent / skill 语义
- 产品特定 workflow ledger、task panel 或 business approval rules

Runtime 应继续拥有的是：

- 低层执行与编排
- 正式扩展边界
- testing 与 observability support
- providers、sessions、permissions、hooks 与 packages 的通用能力

## 6. 总结结论

- 现在成立的是：WeaveRT 不仅证明了 tools、agents、skills、hooks、packages 与 hosts 这些 seams 可用，还把 workflow testing、headless lifecycle helpers、permission presets、result projection、assembly presets、preflight、starter scaffolds 与 workflow observability 都做成了正式公开能力。
- 现在不再成立的是：本文件早期曾把 test kit、lifecycle helpers、permission presets、result-query helpers、hook/package helpers、assembly presets 与 preflight 视为当前缺失项。按 2026-05-04 的仓库状态，这种表述已经不准确。
- 现在更准确的说法是：runtime 工作重点已经从“补基础缺口”转向“收敛采纳路径、减少仓库内部兼容包装层，以及只在真实需求出现时做针对性增强”。

## 7. 已完成路线图回顾

### 7.1 已补齐的基础设施

- 官方 workflow test kit
- 高层 headless workflow runner 与 report helpers
- 非交互 permission presets
- live provider preflight
- 类型化结果查询 helpers
- 轻量 hook 编写 helpers
- 轻量 package builder family
- runtime assembly presets
- 统一 workflow observability model
- runtime starter scaffolds
- 可组合 permission policy framework

### 7.2 更值得继续关注的方向

- 是否继续清理仓库里剩余的 demo-private compatibility wrappers
- 是否继续把 adoption docs、demos 与 starter scaffolds 收敛为更少、更稳定的推荐路径
