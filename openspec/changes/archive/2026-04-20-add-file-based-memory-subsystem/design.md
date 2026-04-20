## Context

当前 runtime 对 memory 只有占位数据模型，没有参考实现风格的默认行为。参考实现的 memory 不是简单 KV store，而是一套明确绑在 session lifecycle 上的控制面语义：

- session startup 加载 `MEMORY.md`
- turn 之前执行 relevant memory retrieval
- 主线程 turn 之后执行 memory extraction
- 以 `user`、`project`、`local` scope 管理不同边界

如果第一版只做抽象 provider 或通用 KV store，用户接口虽然“有 memory”，但 runtime 行为不会像参考实现。

## Goals / Non-Goals

**Goals:**

- 把参考实现风格 memory lifecycle 直接实现为 runtime 的一等子系统。
- 默认以内置文件型 provider 承接 `MEMORY.md`、scope resolution、retrieval 与 extraction 语义。
- 让 memory 通过结构化 fragments 进入上下文装配，而不是变成零散 prompt 拼接。
- 在第一阶段优先保证参考实现语义对齐，而不是过早扩展 backend 自定义能力。

**Non-Goals:**

- 不把第一版 memory 设计成通用 KV store API。
- 不在本变更中实现 long-context compaction orchestration。
- 不在第一阶段开放复杂的第三方 memory provider marketplace。

## Decisions

### 1. 使用 `MemoryManager` + 默认文件型 `MemoryProvider`

runtime 将新增 `MemoryManager`，并以内置文件型 provider 作为第一版默认实现。

Why:

- 参考实现的默认 memory 行为本来就是文件型、session-aware 的。
- 先稳定默认 provider，比一开始开放任意 backend 更符合当前目标。

Alternatives considered:

- 先做通用 KV store。拒绝，因为这无法表达参考实现风格 `MEMORY.md` 与 scope 语义。

### 2. 把 memory 生命周期显式绑定到 session/turn 边界

memory 行为明确分布在三个时点：

- session startup：加载 `MEMORY.md` / entrypoint
- pre-turn：relevant retrieval
- post-turn：主线程 extraction

Why:

- 这与参考实现的 memory lifecycle 一致，也最适合作为可测试 contract。
- 显式边界比隐式 prompt 注入更容易验证。

Alternatives considered:

- 在 PromptComposer 内部临时读取 memory。拒绝，因为这会让加载、检索、提取时序失控。

### 3. memory 贡献通过 fragments 进入上下文装配

memory manager 不直接改写最终 request 文本，而是先生成 entrypoint fragments、retrieved fragments 与 extraction outputs，再由统一上下文装配消费。

Why:

- 这样可以保持 control plane 与 execution plane 分层清晰。
- 也避免 memory 私下修改 prompt 导致与 hooks、compaction 的组合顺序失控。

### 4. 第一版优先保持参考实现默认语义，而不是过早开放自定义

第一版先把默认文件型 memory 与 scopes 做稳，再考虑后续用户自定义 backend。

Why:

- 当前目标是参考实现对齐，不是 memory 平台化。
- 若先开放 backend 扩展点，默认语义很容易被抽空成通用最小公分母。

## Risks / Trade-offs

- **[范围跨层]** memory 会同时影响 bootstrap、session、turn preparation 与 post-turn flow。 → Mitigation: 用 `MemoryManager` 把 lifecycle 收敛成单一入口。
- **[实现简化与语义对齐的张力]** 第一版内部检索算法可能较简化。 → Mitigation: 先对齐 lifecycle、scope 与 orchestration contract，再用 fixtures 补算法细节。
- **[文件边界风险]** memory 读写路径若处理不当会与普通工作目录混淆。 → Mitigation: 显式建模 memory path resolution 与 scope boundary。

## Migration Plan

1. 新增 `MemoryManager`、memory models 与默认文件型 provider。
2. 将 memory path resolution、`MEMORY.md` loading 与 scopes 接入 session startup。
3. 将 relevant retrieval 接入 turn preparation 与上下文装配。
4. 将 post-turn extraction 接入主线程 turn completion。
5. 增加 memory scopes、retrieval、extraction 与 path-boundary 测试。

Rollback strategy:

- 若统一 `MemoryManager` 边界暂时不成立，可回退到 no-op manager，同时保留默认 provider 接口与 lifecycle contract。

## Open Questions

- 第一版 relevant retrieval 是否需要模型参与，还是先使用规则或关键字方案建立 contract？
- `MEMORY.md` 之外是否需要第一阶段就支持额外 memory fragment 文件约定，还是先聚焦参考实现默认入口？
