## 1. Compaction Manager Foundations

- [ ] 1.1 新增 compaction models、`CompactionManager` 与 ordered strategy interface
- [ ] 1.2 明确定义 `CompactionResult`、boundary metadata、summary payload 与 continuation contract

## 2. Turn Preparation Integration

- [ ] 2.1 将 compaction manager 接入 provider request 之前的 turn preparation
- [ ] 2.2 实现 context pressure / policy evaluation 与 compaction trigger path

## 3. Transcript and Resume Safety

- [ ] 3.1 将 compaction boundary/summary 语义接入 session 与 transcript flow
- [ ] 3.2 将 compaction 后 continuation 行为接入 resume path 与 background execution

## 4. Verification

- [ ] 4.1 增加测试，覆盖 strategy orchestration、compaction boundary 与 summary semantics
- [ ] 4.2 增加测试，覆盖 compaction 后的 resume-safe continuation 与 long-session 行为
