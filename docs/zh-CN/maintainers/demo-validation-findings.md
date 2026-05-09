# Demo 验证结论

> 文档说明：这个文件仍然是面向维护者的台账。索引入口请从 `docs/zh-CN/maintainers/validation-findings.md` 开始。

这个文件只保留仓库拥有的 demo findings ledger：在编写 examples 的过程中，哪些 user-centric validation layer 暴露出了哪些 follow-up seams。
如果你是新来仓库的人，请先读 `examples/README.zh-CN.md`，并把这页当成“证据”，而不是起步指南，也不要把它视为路线图承诺。

## 条目模板

- demo：`<demo 模块或短名称>`
- observed issue：`<构建 demo 时暴露出的框架缺口、迷惑契约或缺失 helper>`
- user impact：`<采纳者为什么会在验证 seam 时注意到这个缺口>`
- suggested follow-up area：`<可能需要后续改进的 runtime surface、helper 或 docs 区域>`
- status：`<open | documented | follow-up landed>`

## 当前条目

### guarded_tool_demo

- demo：`guarded_tool_demo`
- observed issue：仓库已经具备 schema validation 与 permission presets 的所有零件，但还没有一个足够小的 helper pattern，把三种最常见的 guarded-tool 检查打包成 starter 级例子。
- user impact：tool authors 仍需要手工拼接 `ToolExecutionSemantics`、`check_permissions` 与 permission preset，才能回答 “被拒绝时会发生什么？”
- suggested follow-up area：tool authoring docs 与 guarded permission patterns 的 demo helpers。
- status：documented

### scoped_agent_delegation_demo

- demo：`scoped_agent_delegation_demo`
- observed issue：child-agent summary 很容易在运行后投影出来，但最直接证明 tool-pool narrowing 的证据仍停留在 request-time turn context，而不是一等运行时 summary 字段。
- user impact：采纳者能确认 delegation 成功，但还要检查 request context 或 tests，才能证明 child 具体还看到了哪些 tools。
- suggested follow-up area：child-run summary payloads 与 delegation diagnostics surfaces。
- status：follow-up landed

### inline_vs_fork_skill_demo

- demo：`inline_vs_fork_skill_demo`
- observed issue：inline skills 通过注入的 system messages 暴露结果，而 fork skills 通过 child summaries 暴露结果。这个对比是稳定的，但如果不把两种模式放在一起看，并不直观。
- user impact：skill authors 如果只看一个 contract surface，可能会选错执行模式。
- suggested follow-up area：skill authoring docs 与 execution-mode 对比说明。
- status：documented

### host_registered_hook_demo

- demo：`host_registered_hook_demo`
- observed issue：host 侧 hook registration 已经稳定，但公开文档还没有突出说明：host registrations 默认是 session-template materialization，并且在内部 inventory 中会显示为 `host_api`。
- user impact：产品集成方虽然能成功注册 hooks，但仍要反复交叉阅读 tests，才能理解为什么 hook 先是 pending，只有 session 存在后才 active。
- suggested follow-up area：host integration docs 中关于 hook materialization 与 inventory terminology 的说明。
- status：documented

### minimal_host_bound_demo

- demo：`minimal_host_bound_demo`
- observed issue：最小 `bind_host()` 路径很紧凑，但采纳者仍需要理解何时用 `bound.run_prompt(...)`、何时用 helper-owned `bound.run_prompt_report(...)`，以及何时用 caller-owned `bound.create_session(...) + bound.run_prompt_report_in_session(...)`，还要知道何时由自己负责 shutdown。
- user impact：第一次集成看起来能跑，但 host 生命周期或 cleanup 问题仍未真正解决。
- suggested follow-up area：host-bound quickstart guidance 与 lifecycle examples。
- status：documented

### stream_report_session_demo

- demo：`stream_report_session_demo`
- observed issue：helper-owned 与 caller-owned report helpers 的大部分行为相同，只有 demo 把 session 是否可复用显式展示出来，这个所有权差异才变得清楚。
- user impact：runtime 采纳者可能会误用 helper-owned 路径，而其实自己需要的是可复用 caller-owned session。
- suggested follow-up area：runtime helper docs 中关于 report ownership 与 session reuse 的说明。
- status：documented

### assembly_diagnostics_demo

- demo：`assembly_diagnostics_demo`
- observed issue：assembly preset provenance、visible invocations 与 route preflight diagnostics 都已经稳定，但用户仍需要跨多个查询 API 才能把这些信息拼起来。
- user impact：用户能回答 assembly posture 问题，但需要跨多处 API 跳转。
- suggested follow-up area：更高层的 assembly diagnostics helper 或更集中式文档。
- status：follow-up landed

### durable_resume_demo

- demo：`durable_resume_demo`
- observed issue：durable resume 在 full distribution 下可用，但最小证明仍需要重新 assemble 再显式调用 `resume()`，比其他轻量 demos 更偏过程化。
- user impact：采纳者能验证 persistence，但不一定能立即看懂这种保证依赖哪些 distribution 与 resume 步骤。
- suggested follow-up area：durable-session docs 与关于 persistence 预期的 preset guidance。
- status：documented
