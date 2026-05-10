# Reactive AI Coding Shell V2

所有命令都从仓库根目录运行。

## 定位

这个应用是仓库里的高级 AI coding integration sample，不是普通框架用户的默认入门路径。
Starter 仍是采纳路径，这个 app 位于验证路径的终点。

## 这个示例证明什么

- 建立在 runtime 之上的 host-owned shell UX
- durable runtime state、approvals 与响应式 workflow 渲染
- 叠加在官方 coding scenario pack 与共享 coding packages 之上的 app-owned customization

## 什么时候使用

- ordinary coding workflow demo 已经讲得通
- 你需要 host-owned UX、durable state、approvals 或 builtin replacement
- 你想看一个高级样例，但不会把它当成默认 starter path

如果你想先走分层验证路径，顺序建议是：

1. `examples/README.zh-CN.md` 里的 seam-basics 和 semantic demos
2. `python3 -B -m examples.projects.coding_workflow_demo`
3. `python3 -B -m examples.projects.coding_workflow_demo --live`
4. `python3 -B -m examples.apps.code_assistant shell`

只有当你明确需要 host-owned UX、durable runtime state、approvals 或 builtin replacement 时，再进入这个 app。

这个 app 在早期 demo 的 durable live-runtime path 基础上，继续叠加面向 coding 的耐久化 `bash` 表面、响应式 runtime observability，以及 app-owned workflow ledger：

- `host`：shell loop、本地命令、approvals、响应式 job/task 渲染、workflow warnings 与 advisories
- `tool`：内置 coding tools，加上 app-specific `bash v2` replacement
- `agent`：`code-assistant`、`coding-planner`、`reviewer`、`verifier`
- `skill`：coding discipline 与可复用的 plan、verify、review workflow skills

## 前置条件

Live workflow turns 需要：

- `OPENAI_API_KEY`

确定性验证路径与 shell 本地命令 smoke 路径不需要 provider 凭据。

可选覆盖：

- `OPENAI_BASE_URL`
- `OPENAI_MODEL`

如果缺少 `OPENAI_API_KEY`，而你又使用 live `run` 路径，或者在 `shell` 中真的消耗了 model turn，这个 app 仍会走内置 live route，并把 provider auth failure 显式暴露出来。

## 可变状态模型

Fixture 是不可变的：

- `examples/apps/code_assistant/fixtures/mini_repo/`

Live app 会编辑生成出来的可变工作区：

- `.local/examples/code_assistant/mini_repo/`

这个可变工作区还会在 `.local/examples/code_assistant/mini_repo/.weavert/` 下保存 durable runtime artifacts，包括 transcripts、child runs、task lists、jobs 与 memory。

## 拆分所有权模型

这个 sample 有意把高级 app 拆分为四个物理部分：

- 位于 `examples/apps/code_assistant/` 下的 app-owned shell layer，负责 host loop、本地命令、approvals、workflow ledger 与 app 配置的 `bash` replacement
- 官方 coding scenario pack，负责 `coding-planner`、`reviewer`、`verifier` 与核心 coding-loop skills
- 共享 git package，负责 `git_*` tool family
- 共享 workspace-intelligence package，负责 `workspace_*` tool family

无论是 live 还是确定性验证路径，都应报告同一组 package-manifest、tool-family 与 definition-owner anchors。

## Shell 模式

先重置可变工作区：

```bash
python3 -B -m examples.apps.code_assistant reset
```

启动交互 shell：

```bash
python3 -B -m examples.apps.code_assistant shell
```

如果你想要非交互 shell session，可使用自动审批：

```bash
python3 -B -m examples.apps.code_assistant shell --auto-approve
```

Shell 会在多个 prompts 之间保持同一个 runtime session，响应式渲染 runtime watchers 产生的 task/job 更新，并支持不会消耗 model turns 的本地命令：

- `/help`
- `/inspect`
- `/resume`
- `/tasks`
- `/jobs`
- `/review`
- `/verify`
- `/exit`

App-local `bash` replacement 保留了公开 tool 名称 `bash`，但 coding-shell 契约支持：

- 现有短命令的 one-shot `exec`
- 由 broker 支撑的长生命周期 shell session `start`、`send`、`read`、`interrupt` 与 `stop`
- 显式的 `line_session` 与 `pty_session` profiles；当 PTY 不可用时会诚实降级
- 位于 `.weavert/shell/` 下的 durable shell sidecars 与共享 job visibility
- 结构化的 command-policy、recovery-state 与 `command_failed` result metadata
- 对 `vim`、`less`、`top` 这类全屏终端 UI 返回显式 unsupported outcomes

### 本地命令 smoke 路径

若只想验证 startup、snapshot、transcript 与 shutdown，而不消耗 model turn：

```bash
python3 -B -m examples.apps.code_assistant reset
python3 -B -m examples.apps.code_assistant shell --session-id local-shell --auto-approve
```

在提示符中执行：

```text
/inspect
/tasks
/jobs
/exit
```

成功锚点包括：

- startup 行，如 `code assistant shell`、`session: local-shell` 与 `workspace: ...`
- `/inspect` 输出中的 `current transcript: local-shell`、`current task list: session:local-shell`、`shell sidecars:`，以及至少一行 `workflow:` snapshot
- 最终 shell report 中的 `transcript: ...`、`child run index: ...` 与 `status: ok`

## Run 模式

### Live workflow run

如果你想跑真实的 planner -> edit -> verify -> review -> summarize 循环，请使用内置 live provider route：

```bash
export OPENAI_API_KEY=your-key
python3 -B -m examples.apps.code_assistant run \
  --session-id live-smoke \
  --auto-approve
```

### 确定性验证运行

如果你想在不需要 live provider 凭据的前提下，验证同一套 split runtime assembly 与 durable artifact layout：

```bash
python3 -B -m examples.apps.code_assistant run \
  --deterministic \
  --session-id deterministic-smoke \
  --auto-approve
```

确定性路径会重放仓库本地 scripted model support，但仍使用同一个 app-owned shell layer、package-backed workflow surfaces、approval handling、task list、workflow ledger、transcript store、child-run store 与 `bash` replacement contract。

两个 `run` 模式的成功锚点包括：

- `mode: live` 或 `mode: deterministic`
- `status: ok`
- `task list: session:<session-id>`
- `workflow: ready_to_summarize (change=2, verified=2, reviewed=2)`
- `package manifests: weavert-scenario-coding, weavert-shared-git, weavert-shared-workspace-intelligence`
- `tool families: git_*=weavert-shared-git, workspace_*=weavert-shared-workspace-intelligence`
- `definition owners: code-assistant=app, coding-planner=weavert-scenario-coding, reviewer=weavert-scenario-coding, verifier=weavert-scenario-coding, coding-loop=weavert-scenario-coding`
- `bash replacement: app-configured v2 over weavert-devtools`
- `transcript: .../.weavert/transcripts/<session-id>.jsonl`
- `child run index: .../.weavert/child_runs/sessions/<session-id>.json`

`run` 路径成功的条件是：workflow 产出真实 planning outcome，在第一次实质编辑前完成仓库检查，验证最新 revision，review 最新 revision，并返回最终摘要。如果 planner 在已经留下可用 shared plan 后才降级，命令仍会成功，并把这一点作为非阻塞的 `workflow advisories` 输出。

## Approval 行为

Host 对 `edit`、`write` 和 `bash` 使用普通 permission path，但 app-local shell policy 现在会给出更明确的审批摘要：

- 默认模式：每次写操作或 shell action 都提示审批
- 对 opaque 或 not-confinable 的 shell commands，会给出显式 policy outcomes，而不是只靠 blacklist 风格阻断
- `--auto-approve`：保持同一套 runtime assembly 与 provider path，但预先回答 host approvals，适合 harness 风格运行

## Coding surfaces

这个 app 在主 coding loop 中复用内置 runtime tools：

- `read`、`glob`、`grep`、`edit`、`write`
- `agent`
- `skill`
- `task_*`、`job_*`

只有 `bash` 被这个 app 本地替换。coding-shell replacement 保留了公开 tool 名称 `bash`，同时增加：

- 面向 `uv run`、`poetry run`、`npm run`、`pnpm run`、`yarn run` 等工作流的 wrapper-aware command policy
- 更清晰的 workspace-aware guardrails、显式的 `blocked` / `not_confinable` outcomes，以及高风险摘要
- 结构化 stdout/stderr 预览
- 由 broker 支撑的长命令后台或 session-oriented job projection
- durable shell sidecars、recovery-state 渲染，以及 sidecar-backed output previews
- 通过 `start`、`send`、`read`、`interrupt`、`stop` 提供的 line-session / PTY-session 生命周期
- 非零 one-shot failures 会作为 `command_failed` 报告，而不会直接压垮整个 coding session

## Workflow ledger

Host 会根据 durable runtime-owned signals 计算 workflow ledger：

- `clean`
- `pending_verification`
- `pending_review`
- `ready_to_summarize`

成功的 `edit` 或 `write` 会推进 change revision，并使旧的 verification/review coverage 失效。成功的 verification 结果以及成功的 reviewer/verifier summaries 会再次推动 session 前进。`/inspect` 和交互 shell 都可以在不消耗额外 model turn 的情况下显示这套状态。

## 可靠成功契约

这个 app 现在明确区分阻塞失败与可见但不阻塞的降级：

- `workflow gaps`：阻塞失败，例如缺少 planner outcome、缺少 pre-edit inspection、缺少 latest-revision verification 或 review coverage
- `workflow advisories`：非阻塞诊断，例如 planner 在已经留下可用 shared task plan 之后才命中 `max_turns`

默认 live task 的 planner 契约刻意保持很窄：先检查 shared task list，只检查修 greeting 所需的文件，留下可见 shared task plan，然后返回简洁摘要。工作区本地 planner 定义使用 `maxTurns: 8`，live prompt 也会用 `max_turns: 8` 调用 planner，因此实际 planner budget 不再被 runtime 额外压低。

## 延后范围

这个 MVP 目前刻意不处理更广泛的产品表面。以下内容仍然延后：

- plugins 与 plugin marketplaces
- MCP integration
- IDE bridges
- worktree automation
- 更广泛的 permissions 产品化工作

## Inspect 与 reset

检查当前 durable state：

```bash
python3 -B -m examples.apps.code_assistant inspect
```

`inspect` 会汇总：

- transcript sessions
- child-run state
- shared task lists
- split app/package assembly 的 package manifests、tool-family owners 与 definition owners
- 过滤掉 `.weavert`、`__pycache__`、`*.pyc`、`*.pyo` 后的语义 changed files
- memory root 与文档数量

`reset` 会删除可变工作区，并从 pristine fixture 重新创建。这样会一起清除 live edits 与 durable runtime artifacts。

## 验收清单

- 不支持的 TUI 命令应返回结构化 unsupported-shell result，而不是把 host 卡死
- 异步 job/task updates 应在交互 shell 中留下可读的提示边界
- `/tasks`、`/jobs` 与 `/inspect` 仍可作为 fallback snapshot 命令使用
- 如果在 ledger 仍处于 `pending_verification` 或 `pending_review` 时 summarize 或 exit，应给出 advisory warning

## 另见

- `../../README.zh-CN.md`
- `../../projects/workspaces/coding_workflow/README.zh-CN.md`
- `../../../docs/zh-CN/guides/use-scenario-packs.md`
- `../../../packages/product-kits/coding/README.zh-CN.md`
- `fixtures/mini_repo/README.zh-CN.md`
