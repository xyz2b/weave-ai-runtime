# 请求生命周期

这页只回答一个问题：一个 prompt 如何在 runtime 中流转？

```text
用户或 Host 输入
  -> session ingress normalization
  -> session 决定是否接纳一个 turn
  -> active context assembly
  -> model invocation
  -> 视需要运行 tools / skills / agents
  -> 必要时做 recovery 或 continuation
  -> terminal turn result
  -> 更新 transcript 与 durable artifacts
```

## 适合谁？

- 正在评估 runtime 在底层如何被组装、执行和持久化的读者。

## 前置条件

- 先读 `../concepts/runtime-model.md`
- 在把这层当作更深的架构层之前，先用 concepts 页面补齐词汇

## 第 1 步：Ingress normalization

Session ingress 会在 turn engine 看见输入之前处理新输入。
它会区分这些关注点：

- normalized messages
- replay outputs
- prompt updates
- private updates

因此，真正决定什么会成为 turn input 的权威是 session，而不是 turn engine。

## 第 2 步：Turn admission

不是每个输入都会变成一个新的 model turn。
Session 会决定这个输入是：

- 更新 transcript-visible history
- 只重放 host-facing output
- 更新私有上下文
- 还是真正接纳一个新 turn

## 第 3 步：Active context assembly

在 model invocation 之前，runtime 会为本次 turn 构建 active context。
这个视图可能包含：

- 选出的 memory fragments
- hook 提供的上下文
- compaction 结果
- session hints 与 attachments

这个投影视图不等于完整 durable transcript。

## 第 4 步：Model 与执行循环

Turn engine 会驱动 model calls、tool use、skill execution 与 agent delegation，直到 turn 达到终态。

这里也是 runtime 负责本地 continuation 的地方，而不会把 tool result 的后续控制完全交给 provider。

## 第 5 步：控制面塑形

Permissions、hooks、memory 与 host interactions 可以影响 turn，但不会接管它的所有权。
例如：

- tool call 可能被拒绝或改写
- 某一步可能需要 host 介入
- recovery policy 可能会给 route failure 分类

## 第 6 步：Attempt-final 与 turn-final

一次 model attempt 可以结束，但整个 turn 还没完成。
这个区分让下面这些事情更容易理解：

- tool continuation
- stop 处理
- 更丰富的 terminal metadata
- recovery decisions

## 第 7 步：Terminal result 与持久化

当 turn 真正结束时，runtime 会更新 transcript，以及所有已配置的 durable artifacts，例如 child-run state、task/job state 与 memory effects。
Host 随后可以渲染或响应这个结果。

## 为什么这个边界重要

它帮助你判断问题来自：

- ingress handling
- context projection
- provider behavior
- tool execution
- host mediation
- persistence 或 recovery

## 下一步

- 如果你需要知道 turn 结束后工件的权威所有者，继续读 `persistence-and-state.md`
- 如果你想影响这里描述的某个生命周期阶段，进入 `../guides/register-hooks.md`
- 如果你需要这些步骤的稳定 observability 投影，进入 `../reference/workflow-observability.md`

## 另见

- `overview.md`
- `persistence-and-state.md`
- `../deep-dives/current-system-architecture.md`
