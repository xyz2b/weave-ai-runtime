## Why

当前 runtime 在 control-plane、turn stream 和 child-run observability 上已经输出了更完整的结构化元数据，但测试和 golden fixture 仍然停留在更早期的最小字段假设上。结果是回归套件开始把“契约扩展”误报成失败，同时还有 compaction 相关测试继续沿用旧的时间戳和 stub 假设，导致套件不能准确表达当前实现的真实契约。

现在需要收口这些测试契约，让 conformance、golden fixture 和 session-memory 回归覆盖与当前 runtime 行为重新对齐。这样后续再演进 terminal metadata、child run record 或 compaction control-plane 时，测试失败才能真正代表行为回归，而不是旧断言没有跟上实现。

## What Changes

- 对齐 turn-stream 与 runtime protocol golden fixture，使 terminal 断言验证稳定必需字段，同时保留 control-plane 增补元数据，而不是把 terminal payload 限死为旧的最小字典。
- 更新 `agent` tool 和 assembled runtime 的回归覆盖，使 child tool result 中的 `terminal_metadata` 与 child run record 的结构化终态元数据保持一致。
- 明确 compaction session metadata 的语义：`last_compaction_at` 只在出现 material compaction effect 时写入，而不是任何 transcript rewrite 都视为一次 compaction。
- 更新 request-assembly 相关测试桩，使 compaction service 通过 `prepare_turn()` 参与 turn preparation，而不是继续依赖只实现 `collect()` 的旧式 stub。
- 刷新这 5 个失败用例及其共用测试辅助代码，使回归套件验证当前 contract，而不是推动 runtime 回退到更弱的行为面。
- 本次变更仅修改测试代码、golden fixture 和测试辅助代码；不调整应用/runtime 实现代码来迎合旧断言。

## Capabilities

### New Capabilities
- None.

### Modified Capabilities
- `agent-delegation`: `agent` tool 的子运行结果需要把结构化 child terminal metadata 作为正式返回契约的一部分。
- `query-turn-stream`: turn terminal event 需要允许 additive terminal metadata，并让回归覆盖验证稳定字段与 discard 语义而不是旧的精简形状。
- `query-runtime-conformance`: golden conformance fixture 需要覆盖 richer terminal metadata，同时保持 interrupt 和 assembled orchestration 的断言稳定。
- `runtime-compaction-manager`: compaction 准备和 session metadata 更新需要围绕 material compaction effect 与 `prepare_turn()` contract 来验证。

## Impact

- Affected tests: `tests/test_agent_skill_runtime.py`, `tests/test_memory_runtime.py`, `tests/test_query_runtime_protocol_golden.py`, `tests/test_query_turn_stream.py`, `tests/runtime_protocol_harness.py`.
- Runtime behavior remains richer than the old assertions: this change updates the documented contract and regression suite to treat additive terminal/control-plane metadata as intentional behavior.
- Out of scope: changes under `src/` or other application/runtime implementation paths.
