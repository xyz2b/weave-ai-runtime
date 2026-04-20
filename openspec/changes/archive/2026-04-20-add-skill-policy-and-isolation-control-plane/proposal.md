## Why

当前 runtime 已经能加载 skill frontmatter 和 agent `isolation` 字段，但这还不是完整的 runtime policy semantics。只有把 skill policy semantics 和 isolation enforcement 补成 control plane，`Tool`、`Agent`、`Skill` 三套用户接口才算真正闭环。

## What Changes

- 引入统一的 skill policy semantics，定义 inline skill、forked skill、subagent delegation、`allowed-tools`、permission inheritance 与 hook ownership 的运行时约束。
- 将 `none`、`worktree`、`remote` 从定义层占位升级为真正的 runtime isolation contract 与 enforcement path。
- 明确 skill、agent、tool 三者之间的 capability narrowing、policy inheritance 与 non-escalation semantics。
- 让 skill 注册的 hooks、tool pool 裁剪、delegated execution context 与 isolation lifecycle 成为可验证的 runtime 行为，而不是 ad hoc wiring。

## Capabilities

### New Capabilities

- `skill-policy-semantics`: 定义 skill 执行模式、capability narrowing、policy inheritance 与 hook ownership。
- `runtime-isolation-control-plane`: 定义 `none`、`worktree`、`remote` 的 runtime isolation contract 与 enforcement behavior。

### Modified Capabilities

## Impact

- 影响 `src/runtime/skill_runtime.py`、`src/runtime/agent_runtime.py`、`src/runtime/tool_runtime.py`、runtime assembly 与 delegated execution path。
- 会把当前 frontmatter 解析与 isolation enum 升级为真正的 runtime enforcement。
- 让后续用户自定义 `Tool`、`Agent`、`Skill` 能在统一 policy/isolation 语义下闭环运行。
