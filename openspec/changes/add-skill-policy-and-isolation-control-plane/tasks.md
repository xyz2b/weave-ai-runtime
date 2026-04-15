## 1. Skill Policy Foundations

- [ ] 1.1 新增 skill policy envelope、policy resolver 与 capability narrowing 模型
- [ ] 1.2 定义 inline skill、forked skill 与 delegated execution 的统一 policy inheritance / non-escalation 规则

## 2. Skill Runtime Integration

- [ ] 2.1 将 `allowed-tools`、permission ceiling、skill-owned hooks 与 subagent inheritance 接入 `SkillRuntime` 与 `AgentRuntime`
- [ ] 2.2 增加测试，覆盖 inline skill、forked skill、hook ownership cleanup 与 delegated execution ceilings

## 3. Isolation Control Plane

- [ ] 3.1 新增 isolation contract、manager 或 adapters，覆盖 `none`、`worktree`、`remote`
- [ ] 3.2 将 isolation enforcement 从局部 cwd helper 迁移到统一 runtime path，并记录 isolation metadata 与 lifecycle

## 4. Verification

- [ ] 4.1 增加测试，覆盖 capability narrowing、permission inheritance、memory/isolation ceilings 与 worktree/remote contracts
- [ ] 4.2 增加诊断或 trace surface，验证 policy resolution 与 isolation enforcement 可观测
