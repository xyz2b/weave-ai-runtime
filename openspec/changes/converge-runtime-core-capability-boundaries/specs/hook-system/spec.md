## MODIFIED Requirements

### Requirement: 参考实现兼容的 runtime hook phases
runtime SHALL 支持一个缩减后的稳定 public hook phase catalog，作为 ordinary framework extension 的 v1 兼容面；其余 hookable lifecycle points SHALL 被视为 advanced 或 internal，而不是默认 public contract。稳定 public phase catalog SHALL 包括 `SessionStart`、`SessionEnd`、`PreToolUse`、`PostToolUse`、`PostToolUseFailure`、`PreModelRequest`、`PostModelResponse`、`Stop`、`Notification`、`Elicitation` 与 `ElicitationResult`。

#### Scenario: 在稳定 public phase 中执行 hook
- **WHEN** 某个 hook 被注册到稳定 public phase catalog 中的某个 phase
- **THEN** runtime SHALL 按该 phase 已发布的 public payload contract 调用该 hook
- **AND** SHALL 将这些 phase 视为 ordinary v1 hook surface 的权威集合

#### Scenario: 高级或内部 phase 不会被默认提升为普通扩展面
- **WHEN** runtime 仍然支持额外 lifecycle points，例如 `UserPromptSubmit`、`SubagentStop`、`PreCompact`、`PostCompact`、`PreContextAssemble`、`PostContextAssemble` 或 `RecoveryDecision`
- **THEN** runtime SHALL 将它们分类为 advanced 或 internal-only，除非未来的 contract revision 明确提升这些 phase
- **AND** SHALL NOT 将这些 phase 作为 ordinary embedders 的 primary public hook surface 进行推广

#### Scenario: 未列入稳定 catalog 的 phase 不属于普通 v1 promise
- **WHEN** 某个接入方依赖未列入稳定 public catalog 的某个 phase
- **THEN** runtime SHALL 将该依赖视为超出 ordinary v1 hook compatibility promise
- **AND** MAY 对该 phase 施加额外 gate、package boundary 或更快的演化节奏

#### Scenario: advanced phase catalog is published separately from the stable set
- **WHEN** an embedder inspects the runtime's public hook-phase contract
- **THEN** the runtime SHALL publish the advanced phase catalog separately from the stable public phase catalog
- **AND** SHALL classify `UserPromptSubmit`、`SubagentStop`、`PreCompact`、`PostCompact`、`PreContextAssemble`、`PostContextAssemble` 与 `RecoveryDecision` as advanced rather than stable ordinary-v1 phases

#### Scenario: unlisted phases remain internal-only
- **WHEN** a hookable lifecycle point is neither in the stable public phase catalog nor in the published advanced phase catalog
- **THEN** the runtime SHALL treat that lifecycle point as internal-only
- **AND** SHALL NOT require embedders to depend on it as part of the public hook contract
