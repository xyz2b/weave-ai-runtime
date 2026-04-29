# hook-system Specification

## Purpose
TBD - created by archiving change python-agent-runtime-foundation. Update Purpose after archive.
## Requirements
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

### Requirement: hooks 可以影响 runtime flow
runtime SHALL 允许 hooks 在对应 phase 允许的前提下追加 context、更新 tool input、阻止 continuation、发出通知或提供 elicitation results。

#### Scenario: pre-tool hook 修改输入
- **WHEN** 某个 `PreToolUse` hook 返回了更新后的 tool input
- **THEN** runtime SHALL 使用更新后的输入执行该 tool call，而不是原始输入

### Requirement: host lifecycle hooks
runtime SHALL 提供用于 startup 和 shutdown 集成的 host lifecycle hooks，使嵌入式 host 能在不修改 turn engine 的前提下接入自定义逻辑。

#### Scenario: CLI host 注册启动逻辑
- **WHEN** 某个 CLI 或 UI host 注册了 startup lifecycle hook
- **THEN** runtime SHALL 在 host 开始处理 interactive session 之前，于 runtime startup 阶段调用该 host hook

### Requirement: Public phase catalog publishes per-phase execution contract
The runtime SHALL publish, for each public hook phase in the authoritative catalog, a per-phase execution contract that defines at least the phase tier, the stable payload contract, the allowed effect classes, and the external-handler eligibility policy for that phase.

#### Scenario: Request-shaping phases declare transform and decide capability
- **WHEN** a caller targets `PreToolUse` or `PreModelRequest`
- **THEN** the public phase contract SHALL declare that those phases accept `observe`
- **AND** the public phase contract SHALL declare whether `transform` and `decide` effects are allowed for those phases

#### Scenario: Observe-oriented phases do not silently become blocking phases
- **WHEN** a caller targets an observe-oriented public phase such as `SessionEnd`, `Notification`, `SubagentStop`, `PreCompact`, or `PostCompact`
- **THEN** the public phase contract SHALL declare those phases as not supporting blocking or request-override semantics unless a future catalog revision explicitly changes that contract

#### Scenario: External-handler eligibility is phase-specific
- **WHEN** a caller registers an external handler kind against a public phase
- **THEN** the runtime SHALL validate that registration against the external-handler eligibility policy published for that phase rather than treating all public phases as equally permissive

### Requirement: Public phase payload schemas define minimum stable fields
The runtime SHALL publish, for each public hook phase in the authoritative catalog, a minimum stable payload schema that names the required public fields for that phase. The runtime MAY add fields in later revisions, but SHALL NOT remove or rename those minimum stable fields without revising the public phase contract.

#### Scenario: Existing kernel-public phases preserve their stable payload fields
- **WHEN** a caller targets an existing kernel-public phase such as `SessionStart`, `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `PostToolUseFailure`, `Stop`, `SubagentStop`, `SessionEnd`, `Notification`, `Elicitation`, `ElicitationResult`, `PreCompact`, or `PostCompact`
- **THEN** the public payload schema SHALL declare the stable identifier and event-specific minimum fields required for that phase

#### Scenario: New control-plane phases publish stable minimum fields
- **WHEN** a caller targets a control-plane-public phase such as `PreContextAssemble`, `PostContextAssemble`, `PreModelRequest`, `PostModelResponse`, or `RecoveryDecision`
- **THEN** the public payload schema SHALL declare the minimum stable fields required to reason about that phase without relying on internal-only runtime structures

#### Scenario: Public payload does not expose private runtime carriers directly
- **WHEN** a public phase needs to surface request-shaping state, response state, or runtime metadata to a hook
- **THEN** the runtime SHALL expose that information through a stable public view or envelope rather than requiring hooks to depend on private-only carrier structures or mutable runtime handles

