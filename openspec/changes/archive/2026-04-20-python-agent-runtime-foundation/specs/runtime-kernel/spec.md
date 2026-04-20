## ADDED Requirements

### Requirement: Python runtime kernel 引导
runtime SHALL 提供一个 Python runtime kernel，用于从 bundled 和用户提供的 runtime definitions 引导 configuration、registries、persistence wiring 与默认子系统。

#### Scenario: 使用 bundled 与用户定义启动 kernel
- **WHEN** runtime 在 bundled definitions 与引用了 custom tools、agents、skills、memory settings 和 hooks 的用户配置下启动
- **THEN** runtime SHALL 在任何 conversation session 开始前构建对应的 registries 与 subsystem instances

### Requirement: 显式 session controller
runtime SHALL 暴露一个 `SessionController`，在 turn execution 开始前将来自 host 的输入事件归一化到单一的 session command flow 中。

#### Scenario: 不同 hosts 共享一套 session flow
- **WHEN** 一个 CLI host 与一个 SDK host 分别向同一 runtime contract 提交用户 prompt
- **THEN** runtime SHALL 通过同一套 session command lifecycle 归一化两类输入，而不是依赖 host-specific control logic

### Requirement: 与 host 无关的 turn engine
runtime SHALL 通过一个与 host 无关的 turn engine 执行 conversational turns，该 turn engine 必须能够同时复用于 interactive 与 headless hosts。

#### Scenario: turn engine 不依赖 UI 所有权
- **WHEN** 某个 host adapter 启动一个新的 turn
- **THEN** runtime SHALL 通过 turn engine 处理 prompt composition、model interaction、tool orchestration 与 turn completion，而不要求 host 自己实现这些行为
