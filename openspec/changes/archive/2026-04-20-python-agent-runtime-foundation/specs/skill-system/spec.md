## ADDED Requirements

### Requirement: 参考实现兼容的 skill 定义
runtime SHALL 支持使用参考实现兼容 `SKILL.md` 形式编写的 skill definitions，包括用于 description、model selection、effort、tool restrictions、hooks、execution mode 与 invocation behavior 的 frontmatter 字段。

#### Scenario: 从 SKILL.md 加载 skill
- **WHEN** runtime 在支持的 skill 目录中发现一个有效的 `SKILL.md` 文件
- **THEN** runtime SHALL 使用参考实现兼容的 frontmatter 语义加载该 skill

### Requirement: skill discovery 与 activation
runtime SHALL 支持 bundled、user 与 project 范围内的 skill discovery，并支持 conditional activation rules。

#### Scenario: 激活 path-scoped skill
- **WHEN** 某个 skill 声明了基于路径的 activation metadata，且当前 session 命中这些路径
- **THEN** runtime SHALL 仅在 activation condition 满足时将该 skill 暴露给当前 session

### Requirement: skill execution modes
runtime SHALL 支持参考实现兼容的 skill execution 行为，包括直接 prompt injection，以及通过专用 agent context 执行的 forked execution。

#### Scenario: 执行 forked skill
- **WHEN** 某个 skill 被配置为 forked execution mode
- **THEN** runtime SHALL 在隔离的 agent context 中执行该 skill，而不是把它当成普通 inline prompt fragment
