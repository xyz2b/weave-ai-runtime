## Context

这次变更不是引入新的 runtime 功能，而是把回归测试、golden fixture 和当前 control-plane 契约重新对齐。现状是 runtime 已经会在 terminal surfaces、child run records 和 compaction pipeline 中输出更完整的结构化信息，但部分测试仍然把这些面当成旧式最小 payload 来断言，导致 5 个失败都更接近“测试桩或断言过期”而不是实现真的回归。

这几个失败分布在不同模块，但它们共享同一个根因：测试没有把 runtime 现有的 authoritative contract 当成唯一真相。具体表现为：

- terminal 事件和 child tool result 已经携带 additive metadata，测试却仍然用精确字典相等把 payload 限死。
- session compaction metadata 已经依赖 material compaction effect，测试却把任意 `_apply_compaction()` transcript rewrite 都当成真实 compaction。
- compaction control-plane 已经通过 `prepare_turn()` 进入 turn preparation，测试 stub 却只实现了旧式 `collect()`。

## Goals / Non-Goals

**Goals:**

- 让 turn-stream、runtime protocol golden、agent tool 和 session memory 的回归覆盖反映当前 runtime contract。
- 明确 terminal metadata 是可扩展结构，而不是只能有 `stop_reason` / `request_id` 的固定形状。
- 明确 compaction timestamps 只在 material compaction effect 发生时更新。
- 让测试中的 compaction service stub 遵守 `prepare_turn()` contract，从而覆盖真实的 request assembly 路径。
- 仅通过测试、fixture 和测试辅助代码收口这些差异，不改动应用/runtime 实现。

**Non-Goals:**

- 不把 runtime payload 回退到旧的最小字段形状。
- 不在这次 proposal 中引入新的 control-plane 子系统或重构 main loop。
- 不处理与这 5 个失败无关的文档或测试清理。
- 不修改 `src/` 下的应用代码或任何 runtime 实现逻辑。

## Decisions

### Decision: Keep richer terminal metadata and update tests around stable subsets

运行时当前已经把 `turn_result.metadata`、terminal metadata、provider stop reason、control-plane metadata 和 post-effect hints 合并到 terminal surfaces 中。回退这个行为只会让 observability 变弱，也会让 host/child-run surfaces 再次分裂。

因此这次变更选择保留 richer metadata，并在测试中区分：

- 必需字段：`stop_reason`、`request_id`、`abort_reason` 等稳定字段必须继续验证。
- 扩展字段：control-plane 和 provider 附加字段允许存在，并需要在 relevant fixture 中被保留。

备选方案是把实现改回旧的最小 payload，但这会损失当前已经可用的结构化观测面，因此不采用。

### Decision: Resolve the failures strictly in test surfaces

这 5 个失败都已经能解释为测试期望、fixture shape 或 stub contract 落后于当前 runtime 行为，因此本次变更只允许在测试文件、golden fixture 和测试辅助代码内收口差异。

备选方案是通过修改 runtime 代码来重新适配旧断言，但这会把已经成型的 contract 往回拉，且无法证明这些失败真的是实现问题，因此不采用。

### Decision: Treat child tool results and child run records as one terminal source of truth

`agent` tool 的返回 payload 不应重新发明一个“缩水版 terminal summary”。更稳妥的做法是让 tool result 的 `terminal_metadata` 与 child run record 持续对齐，这样 assembled runtime、tool caller 和 host 看到的是同一套终态信息。

备选方案是单独维护一份更窄的 tool payload schema；这样短期看断言更简单，但长期会制造 child-run observability 和 tool result contract 的重复定义，因此不采用。

### Decision: Drive compaction regressions through effect metadata, not direct helper invocation alone

`_apply_compaction()` 现在承担 transcript rewrite 和 session metadata persistence 两个层面，但 `last_compaction_at` 只应该在真正的 compaction effect 被记录时更新。测试需要围绕这个 contract 建模，而不是把 helper 调用本身等同于 material compaction。

备选方案是让 `_apply_compaction()` 无条件写 compaction timestamp。这样会把普通 rewrite、repair 或 refresh 也伪装成 compaction，污染 session metadata，因此不采用。

### Decision: Make `prepare_turn()` the authoritative compaction test seam

当前 turn preparation 会优先走 compaction service 的 `prepare_turn()` contract。测试如果继续只提供 `collect()`，实际上覆盖不到真实路径，还会在请求发出前直接报错。

因此这次变更会把相关测试桩切换到 `prepare_turn()` entrypoint，必要时再补充 `collect()` 以覆盖向后兼容路径。备选方案是让运行时为旧 stub 隐式兜底，但这会继续模糊 control-plane contract，因此不采用。

## Risks / Trade-offs

- [Risk] 测试从“精确相等”改为“验证稳定子集”后，可能放过某些不该出现的元数据变化。 → Mitigation: 对 stable keys、关键 nested fields 和 child/run alignment 继续做显式断言，不改成完全宽松匹配。
- [Risk] 只调整测试可能掩盖极少数真实契约漂移。 → Mitigation: 在实现阶段先比较 spec、runtime surface 和 failing assertion，只有确认 runtime 已经符合期望 contract 时才更新 fixture。
- [Risk] compaction 语义的测试更新可能遗漏 transcript rewrite 的其他路径。 → Mitigation: 分开覆盖“material compaction”和“non-compaction rewrite”两类路径，避免只保留单一路径断言。

## Migration Plan

1. 先更新 spec delta，明确 terminal metadata、child tool result 和 compaction effect 的正式 contract。
2. 按 spec 更新测试辅助代码和 failing tests，优先修复 shared harness。
3. 重新运行对应的 targeted tests，确认 regression suite 对齐当前 runtime behavior。
4. 最后跑完整 pytest 套件，确认没有引入新的 contract mismatch。

这次变更没有外部部署或数据迁移要求；失败时可通过回滚测试与 spec delta 一起撤销。

## Open Questions

- 当前 terminal metadata 中哪些 control-plane nested fields 应被 golden fixture 固定下来，哪些只需要验证存在性，还需要在实现时做最后取舍。
- `agent` tool result 是否需要在 spec 中进一步区分“必需 terminal fields”和“透传 terminal metadata”；本 proposal 先以与 child run record 对齐为准。
