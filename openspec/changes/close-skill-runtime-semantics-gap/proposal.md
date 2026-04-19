## Why

Claude Code 中的 skill 本体不是一段提示词文本，而是 `prompt body + typed metadata + runtime policy envelope`。当前 runtime 已经支持 Claude Code 风格 skill 的定义加载、部分 policy narrowing、forked execution、hook ownership 与 invocation catalog，但仍有几类关键 frontmatter 字段停留在“已解析、未完全执行”的状态。

这个缺口让 skill 的真实行为与 Claude Code 不一致，也让 host、model 和实现者都难以稳定推理 skill 何时可见、何时激活、以及哪些约束会真正生效。

## What Changes

- 明确将 skill 视为 `prompt + metadata + runtime policy` 的统一运行时对象，而不是仅把 `SKILL.md` body 注入上下文。
- 为 skill 增加完整的 runtime semantics，而不只是在 `SkillDefinition` 中保存 frontmatter 字段。
- 引入显式的 skill activation lifecycle，区分 discovered、eligible、active、user-invocable、model-invocable 等状态，并让 path/file 观测驱动激活。
- 为 inline skill 补齐 prompt expansion 与 shell execution 语义，包括参数替换、`${CLAUDE_SESSION_ID}`、`${CLAUDE_SKILL_DIR}` 与 `shell` 选择。
- 让 skill 级别的 `model` 与 `effort` override 在 inline 与 forked 两条执行路径中都真正进入请求构建与子执行上下文。
- 统一 skill invocation gate，使 `user-invocable`、`disable-model-invocation`、path activation、policy narrowing 与 diagnostics 使用同一套判定链路。
- 为上述语义补齐回归测试与可观测 metadata，避免再次退化成“字段存在但没有 runtime effect”。

## Capabilities

### New Capabilities
- `skill-runtime-semantics`: 定义并执行 Claude Code 风格 skill 的 runtime policy envelope，包括 prompt expansion、shell execution、model/effort override 与统一 invocation gate。
- `skill-activation-lifecycle`: 定义 skill metadata 在 discovery / activation / visibility 阶段的生命周期，包括 path-scoped skill 的发现、资格判定、激活与稳定诊断面。

### Modified Capabilities

## Impact

- Affected code:
  - `src/claude_agent_runtime/registries/discovery.py`
  - `src/claude_agent_runtime/definitions.py`
  - `src/claude_agent_runtime/registries/skill_registry.py`
  - `src/claude_agent_runtime/invocation_catalog.py`
  - `src/claude_agent_runtime/skill_runtime.py`
  - `src/claude_agent_runtime/turn_engine/engine.py`
  - `src/claude_agent_runtime/runtime_kernel/kernel.py`
  - `tests/test_discovery.py`
  - `tests/test_invocation_catalog.py`
  - `tests/test_agent_skill_runtime.py`
- Affected systems:
  - skill discovery and activation
  - invocation visibility and diagnostics
  - turn request composition
  - inline and forked skill execution
- External APIs: none
- Dependencies: reuse existing hook, isolation, permission, and tool execution control planes; no new external dependency required
