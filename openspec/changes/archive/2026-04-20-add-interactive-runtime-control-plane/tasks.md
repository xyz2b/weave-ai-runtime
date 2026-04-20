## 1. Hook Bus Foundations

- [x] 1.1 新增 `HookBus`、hook registry、hook execution result 与 session-scoped ownership 模型
- [x] 1.2 实现 Claude 兼容 runtime phases 的 dispatch、matcher 解析与 structured effect 聚合

## 2. Permission and Elicitation

- [x] 2.1 新增 `PermissionContext`、`PermissionOutcome`、rules model 与默认 `PermissionEngine`
- [x] 2.2 新增 `ElicitationRequest`、`ElicitationResponse` 与共享 `ElicitationService`
- [x] 2.3 将 `check_permissions`、`permission_handler`、`ask_user_handler` 迁移到统一控制流

## 3. Host Bridge

- [x] 3.1 将现有 host abstraction 扩展为覆盖 lifecycle、permission、elicitation、notification 与 turn-event emission 的 `HostRuntime` contract
- [x] 3.2 更新 `BoundHostRuntime` 与 runtime assembly，使 host runtime 成为正式绑定对象而不是 lifecycle-only stub
- [x] 3.3 实现最小 CLI host 与 SDK host reference adapters

## 4. Runtime Integration and Verification

- [x] 4.1 将 HookBus、PermissionEngine、ElicitationService 与 HostRuntime 接入 `SessionController`、`TurnEngine`、`ToolRuntime`、`SkillRuntime` 与 subagent path
- [x] 4.2 增加 updated input、blocked continuation、permission modes、hook-satisfied elicitation、host-mediated elicitation 与 host lifecycle 的测试
