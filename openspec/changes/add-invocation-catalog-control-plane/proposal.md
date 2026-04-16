## Why

当前 runtime 的 skill system 已经具备较强的 execution semantics，包括 `SKILL.md` frontmatter 解析、inline / fork execution、`allowed-tools` capability narrowing、hook ownership 与 permission / isolation ceiling inheritance。但它仍缺少一层独立的 invocation/catalog control plane，因此还不能稳定回答“某个 skill 在当前上下文是否可见、是否允许用户调用、是否允许模型调用，以及为什么不可用”。

现在补齐这层控制面，能把当前实现从“skill policy runtime 已经成立”推进到“capability exposure contract 也成立”。这既能修复 path-scoped activation 与可见性语义不完整的问题，也能为后续 slash command、plugin command 与 MCP prompt 接入预留统一边界，而不把 CLI 表面绑定成 runtime 本体。

## What Changes

- 引入独立的 invocation catalog control plane，包括 invocation definition、provider、registry、session-scoped resolution context 与 diagnostics surface。
- 将 skill 视为 invocation source 的一种，而不是唯一的 invocation 形态；保留现有 `SkillExecutor` 作为 skill execution backend。
- 将 `paths`、`user-invocable`、`disable-model-invocation`、`argument-hint` 等 frontmatter 字段从“已解析 metadata”升级为实际 runtime visibility / invocability semantics。
- 让 path-scoped invocation 在 session-scoped resolution 中按真实上下文求值，而不是停留在 registry-only 过滤；无法证明命中时默认隐藏，而不是默认暴露。
- 为 host 暴露 invocation diagnostics，解释某个 invocation 为什么当前不可见、不可调用或被 policy 收窄。
- 保持 `main-router` 继续承担 root routing agent 角色，但让它消费 resolved capability exposure，而不是直接依赖原始 registry 集合。
- 第一阶段不强行以通用 command tool 取代 builtin `skill` tool；先统一 catalog / visibility，再决定是否向模型暴露 generic invocation surface。

## Capabilities

### New Capabilities
- `invocation-catalog`: 统一聚合 invocable capabilities，并以 session-scoped context 解析可见性、用户可调用性与模型可调用性。
- `invocation-diagnostics`: 向 host 和 runtime 暴露 invocation visibility / invocability 的诊断结果与原因。

### Modified Capabilities

## Impact

- Affected code: `src/claude_agent_runtime/definitions.py`, `src/claude_agent_runtime/registries/discovery.py`, `src/claude_agent_runtime/registries/skill_registry.py`, `src/claude_agent_runtime/runtime_kernel/kernel.py`, `src/claude_agent_runtime/runtime_kernel/config.py`, `src/claude_agent_runtime/contracts.py`, `src/claude_agent_runtime/turn_engine/composer.py`, `src/claude_agent_runtime/turn_engine/engine.py`, `src/claude_agent_runtime/tool_runtime.py`, `src/claude_agent_runtime/skill_runtime.py`, and host-facing runtime surfaces.
- Affected behavior: skill exposure, path-scoped activation, user/model invocability, root capability presentation, and runtime diagnostics.
- Follow-on integration points: slash-command adapters, plugin command providers, and MCP prompt providers can attach to the new provider pipeline without redefining execution policy semantics.
