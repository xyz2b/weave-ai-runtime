# hook-system Specification

## Purpose
TBD - created by archiving change python-agent-runtime-foundation. Update Purpose after archive.
## Requirements
### Requirement: 参考实现兼容的 runtime hook phases
runtime SHALL 支持与参考实现兼容的 runtime hook phase 名称与契约，并 SHALL 把对外 hook 生命周期分层为 `kernel public`、`control-plane public` 与 `internal-only` 三类稳定性层级。public hook phases SHALL 同时覆盖 reference-compatible session、prompt、tool、stop、elicitation、compact、notification 与 subagent lifecycle events，以及 framework-oriented 的 context assembly、model request / response handling 和 recovery decision phases。

#### Scenario: 在参考实现兼容 phase 中执行 hook
- **WHEN** 某个 hook 被注册到 `SessionStart`、`UserPromptSubmit`、`PreToolUse`、`PostToolUse`、`Stop`、`SubagentStop` 或 `SessionEnd` 等参考实现兼容事件上
- **THEN** runtime SHALL 在对应 runtime phase 中，按照该事件定义的 hook payload contract 调用该 hook

#### Scenario: 在 framework-oriented public phase 中执行 hook
- **WHEN** 某个 hook 被注册到 `PreContextAssemble`、`PostContextAssemble`、`PreModelRequest`、`PostModelResponse` 或 `RecoveryDecision` 等 public control-plane event 上
- **THEN** runtime SHALL 在对应 main-loop boundary 触发该 phase，并 SHALL 为该 phase 提供稳定的 payload contract 与 stability tier

#### Scenario: 首批 public phase catalog 是权威契约
- **WHEN** 某个接入方依赖当前 runtime 版本的公开 hook 生命周期
- **THEN** runtime SHALL 将 `SessionStart`、`UserPromptSubmit`、`PreToolUse`、`PostToolUse`、`PostToolUseFailure`、`Stop`、`SubagentStop`、`SessionEnd`、`Notification`、`Elicitation`、`ElicitationResult`、`PreCompact` 与 `PostCompact` 视为首批 `kernel public` phase
- **AND** runtime SHALL 将 `PreContextAssemble`、`PostContextAssemble`、`PreModelRequest`、`PostModelResponse` 与 `RecoveryDecision` 视为首批 `control-plane public` phase

#### Scenario: Internal-only phase 不会被误认为 public contract
- **WHEN** runtime 内部引入仅用于实现的临时 phase
- **THEN** runtime SHALL 将该 phase 标记为 `internal-only`，并 SHALL NOT 要求外部 authoring surface 或 integration contract 依赖它

#### Scenario: Unlisted phase 默认为 internal-only
- **WHEN** 某个 hookable runtime phase 没有被列入当前版本的 public phase catalog
- **THEN** runtime SHALL 将该 phase 视为 `internal-only`
- **AND** runtime SHALL NOT 要求外部 authoring surface、host integration contract 或 compatibility promise 依赖它

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

