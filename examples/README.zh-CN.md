# Runtime 示例

这个页面是仓库的 examples 索引，也是验证路径入口。
所有命令都从仓库根目录运行。示例模块会自动把每个工作区的 `packages/**/src/` 根加入环境，因此不需要先做 editable install。

公开的离线 workflow testing kit 现在位于 `weavert_testing`。
Seam、skill 和 project demos 都复用这套共享工具链，因此默认验证路径保持确定性，也不要求外部模型凭据。

如果你是在启动一个全新的 WeaveRT 项目，请先从 `docs/zh-CN/getting-started/starter-scaffolds.md` 的官方 starter scaffolds 开始。这个目录里的 demos 是验证路径，不是默认采纳路径。

## 这页是干什么的

- 在 starter 跑通后，选择最小但有用的验证步骤
- 一次验证一个 runtime seam，再逐步进入更大的 workflow
- 只有在理解普通路径之后，才去看仓库里的高级 integration samples

## 什么时候用它

- 你已经有一个由 starter 生成、或以其他方式可工作的 runtime baseline
- 你想看仓库自带的验证证据，而不是新项目脚手架
- 你需要用可运行命令证明某个 seam、workflow layer 或 app-integration boundary

## 分层验证路径

这个仓库把可运行 demos 组织成一条分层验证路径，而不是平铺目录：

1. `Seam basics`：一次验证一个稳定扩展表面。
2. `User-centric validation`：回答采纳者最常见的问题，如 guarded tools、scoped delegation、host binding、report ownership、diagnostics 与 durable resume。
3. `Semantic demos`：验证当 hooks 或 packages 改变 runtime contract 时，这些表面如何表现。
4. `Project demos`：验证更真实的 workflow，但仍停留在普通扩展路径上，使用工作区本地定义和内置 runtime surfaces，而不要求 custom host binding 或 builtin replacement。
5. `Workflow-level live smoke`：用内置 live provider route 运行同一 coding workflow 与 fixture。
6. `Advanced live app demos`：验证 `bind_host()`、durable state、approvals 与 builtin replacement 这类产品级 integration seams。

每个 demo 条目都带两个导航线索：

- `Integration posture`：说明它处于稳定公开 seam、普通扩展路径、live-smoke 升级路径，还是高级 host-bound app 路径。
- `Use this when`：回答 “什么时候该跑这个 demo，而不是另一个？”

推荐起步顺序：

- 如果你是普通框架用户，要新建项目，先生成 starter，再回到这里验证公开 seams。
- 如果你要看仓库级验证，从 `Seam basics` 开始，再进入 `User-centric validation`。
- 如果你接下来需要 hook 或 package 形状的 contract changes，再看 `Semantic demos`。
- 然后运行 `python3 -B -m examples.projects.coding_workflow_demo`。
- 如果离线 coding workflow 通过了，并且你还想看 provider-backed 证据，再运行 `python3 -B -m examples.projects.coding_workflow_demo --live`。
- 如果你需要 host-owned UX、durable runtime state 或 builtin replacement，再进入 `examples/apps/code_assistant/`。

## Live 验证前置条件

下方 seam、user-centric、semantic 和默认 project 表格都是有意设计为离线且确定性的。
如果你只是为了学习框架表面，可以停留在这条路径上，不必导出 provider 凭据。

如果你要进入 live 验证层，请设置：

- `OPENAI_API_KEY`（必需）
- `OPENAI_BASE_URL`（可选）
- `OPENAI_MODEL`（可选，默认 `gpt-4.1-mini`）

## Seam basics

| Demo | Integration posture | Extension seam | Use this when | Run command | Expected output |
| --- | --- | --- | --- | --- | --- |
| File-backed tool | Stable public seam | `.weavert/tools/*.py` | 你想先证明文件型 tool 的发现与执行没问题，再去组合更大的 workflow。 | `python3 -B -m examples.tools.file_backed_tool_demo` | 输出 `available tools: report_status` 和确定性的 tool result payload。 |
| File-backed agent | Stable public seam | `.weavert/agents/*.md` | 你想先确认文件型 agent 的发现与 prompt ownership，再去叠加 tools 或 skills。 | `python3 -B -m examples.agents.file_backed_agent_demo` | 输出 `agent: release-reviewer` 以及该 agent 的简短审批回复。 |
| File-backed skill | Stable public seam | `.weavert/skills/**/SKILL.md` | 你想先证明一个已发现的 skill 能运行并 fork 子 agent，而不是直接进入更大编排。 | `python3 -B -m examples.skills.file_backed_skill_demo` | 输出 `skill: release-summary`、`mode: fork` 和 child-agent reply。 |
| Session hook | Stable public seam | `session.hooks.on_pre_tool_use(...)` | 你需要先验证一个 per-session hook rewrite，再把 hooks 混进 packages、workflows 或 host code。 | `python3 -B -m examples.hooks.session_register_hook_demo` | 输出 `hook activation: active`，并展示 hook 改写后的 `echo` 结果。 |
| Capability-only package | Stable public seam | `build_capability_only_package_manifest()` | 你想先看 package admission 与 capability binding 的最小证明，再加 context contributors 或 providers。 | `python3 -B -m examples.packages.capability_only_package_demo` | 输出解析后的 capability payload，以及 package owner 与 manifest metadata。 |
| Context-contributor-only package | Stable public seam | `build_context_contributor_only_package_manifest()` | 你想在没有额外 capability 或 invocation surfaces 的情况下验证 package 提供的上下文或 hook 注入。 | `python3 -B -m examples.packages.context_contributor_only_package_demo` | 输出注入的 hook fragment 与 contributor owner metadata。 |
| Provider-only package | Stable public seam | `build_provider_only_invocation_package_manifest()` | 你想单独验证 invocation-provider visibility，而不是更大的 package composition。 | `python3 -B -m examples.packages.provider_only_package_demo` | 输出 `visible invocations: package-release-check` 与 provider registration metadata。 |
| General package contribution | Stable public seam | `RuntimePackageManifest` + `PackageContribution` | 你想看一个紧凑示例，展示多个 package contribution surfaces 如何一起工作。 | `python3 -B -m examples.packages.general_package_demo` | 输出 capability payload，以及 package 注入的 hook-stage context fragment。 |

## User-centric validation

这些 demos 位于 seam basics 与更完整 workflow samples 之间。它们聚焦回答采纳者问题，保持每次验证边界狭窄，并能与 `docs/maintainers/demo-validation-findings.md` 中的仓库级 findings ledger 对应起来。维护者视角的索引见 `docs/zh-CN/maintainers/validation-findings.md`。

### 聚焦 seam 问题

| Demo | Integration posture | Use this when | Run command | Stable anchors | Why before project demos |
| --- | --- | --- | --- | --- | --- |
| Guarded tool | Focused tool-contract validation | 你想在把 tool 接进更大 workflow 之前，先验证自定义输入 guard、schema error、permission denial 与成功路径。 | `python3 -B -m examples.tools.guarded_tool_demo` | `demo: guarded tool`、`schema validation: rejected invalid input`、`permission path: denied`、`status: ok` | 先把 tool contract 单独证明，再去更大 agent loop。 |
| Scoped agent delegation | Focused delegation validation | 你想知道委派给一个更窄 tool pool 的 child agent 时，到底发生了什么变化。 | `python3 -B -m examples.agents.scoped_agent_delegation_demo` | `demo: scoped agent delegation`、`visible tools:`、`scope tools:`、`child summary:`、`status: ok` | 它能在进入项目 workflow 前，先证明 request-time tool narrowing 与 `scope_summary`。 |
| Inline vs fork skill | Focused skill-mode validation | 你想决定一个 skill 该保持 inline，还是 fork 到子 agent。 | `python3 -B -m examples.skills.inline_vs_fork_skill_demo` | `demo: inline vs fork skill`、`inline result:`、`fork child summary:`、`status: ok` | 先把执行模式差异看清，再进入更大组合。 |
| Host-registered hook | Focused host-hook validation | 你想从 host-owned 集成代码里接入 hook，确认它会 materialize 成 active session hook，并真的触发。 | `python3 -B -m examples.hooks.host_registered_hook_demo` | `demo: bound.hooks.on_pre_tool_use`、`hook source: host`、`hook activation: active`、`status: ok` | 它比完整产品 shell 更小，却能展示规范的 bound-host 报告路径。 |

### 最小 host 集成

| Demo | Integration posture | Use this when | Run command | Stable anchors | Why before advanced app samples |
| --- | --- | --- | --- | --- | --- |
| Minimal host-bound | Minimal host-bound seam | 你想看最小的稳定 `RuntimeAssembly.bind_host()` 路径，同时还能看到 lifecycle 与 turn events。 | `python3 -B -m examples.hosts.minimal_host_bound_demo` | `demo: minimal host-bound`、`host lifecycle: startup, ready, shutdown`、`turn terminal observed: true`、`status: ok` | 先证明 host seam，再引入 approvals、durable state 或 builtin replacement。 |

### Runtime helper 与 diagnostics

| Demo | Integration posture | Use this when | Run command | Stable anchors | Why before project demos or advanced apps |
| --- | --- | --- | --- | --- | --- |
| Stream/report session | Runtime helper validation | 你想知道是谁拥有 session，以及如何证明调用方拥有的 session 仍可复用。 | `python3 -B -m examples.runtime.stream_report_session_demo` | `demo: stream/report session`、`helper-owned report: completed`、`session reusable: true`、`status: ok` | 直接回答 helper 生命周期问题，不把它埋进更大 workflow。 |
| Assembly diagnostics | Runtime diagnostics validation | 你想在没有产品 UX 的情况下，检查 assembly posture、visible invocations 与可预测的 model-route failure。 | `python3 -B -m examples.runtime.assembly_diagnostics_demo` | `demo: assembly diagnostics`、`assembly preset:`、`visible invocations:`、`failure class:`、`status: ok` | 用统一 posture helper 暴露 assembly 与 route diagnostics。 |
| Durable resume | Durable-state seam validation | 你想在构建自定义产品 UX 之前，先看 durable transcript 与 resume 的最小证明。 | `python3 -B -m examples.runtime.durable_resume_demo` | `demo: durable resume`、`turn one persisted: true`、`session resumed: true`、`status: ok` | 直接验证 persistence 预期，而不是绕到高级 app shell。 |

## Semantic demos

| Demo | Integration posture | Extension seam | Use this when | Run command | Expected output |
| --- | --- | --- | --- | --- | --- |
| Inline skill hooks | Semantic contract variation | skill frontmatter `hooks` + `context: inline` | 你想看到 hooks 跟随 skill invocation 移动，并在 inline skill 结束后释放。 | `python3 -B -m examples.skills.inline_skill_hook_demo` | 输出 `first turn result: rewritten` 和 `second turn result: original`。 |
| Runtime config hook | Semantic contract variation | `RuntimeConfig(hooks=...)` | 你想让 hook activation 成为默认 assembly 行为，而不是 per-session 注册。 | `python3 -B -m examples.hooks.runtime_config_hook_demo` | 输出 `hook source: runtime_config`，并展示两个 sessions 中的相同结果。 |
| Package activation | Semantic contract variation | `RuntimeConfig.extra_package_manifests` vs `RuntimeConfig.requested_packages` | 你想把 package admission 与 activation 分开，并观察 invocation visibility 的变化。 | `python3 -B -m examples.packages.package_activation_demo` | 先输出 admitted-but-inactive，再输出 active 后可见的 `package-release-check`。 |

在验证完 user-centric layer 和你关心的 semantic variations 之后，再进入 project layer，看这些公开 surfaces 如何组合成真实 workflow。

## Project demos

这些 demos 停留在 ordinary extension path 上。它们使用工作区本地 `.weavert/` 定义与内置 runtime surfaces，不需要 custom host binding 或 builtin replacements。

| Demo | Integration posture | Use this when | What it validates | Run command | Expected output |
| --- | --- | --- | --- | --- | --- |
| Release workflow | Ordinary extension path | 你想看一个完整但离线的 release-readiness workflow，同时仍停留在默认 runtime 扩展故事中。 | 对小型项目工作区做一套离线 release-readiness review。 | `python3 -B -m examples.projects.release_workflow_demo` | 输出发现到的工作区事实、release-freeze 上下文、child summary 与最终 verdict。 |
| Coding workflow | Ordinary extension path | 你想看一个真实的 inspect -> edit -> verify -> review 循环，但不进入 host-owned UX 或 builtin replacement。 | 在小工作区里做一次 bugfix 风格的 inspect -> edit -> verify -> review loop。 | `python3 -B -m examples.projects.coding_workflow_demo` | 输出 `mode: offline`、`verification: passed`、`review: pass`、`status: ok`。 |

## Headless permission presets

当你从交互式 demos 转向 CI、smoke 或脚本化运行时，优先使用 runtime-owned permission presets，而不是手写 stubs：

- `AllowAllPermissionService`：适合已 sandbox 好、且你不想在 host 里弹确认的快速 smoke。
- `DenyAllPermissionService`：适合严格 CI，任何意外 tool、skill 或 child-agent permission 请求都应失败关闭。
- `ReadOnlyPermissionService`：适合 inspect-only workflows、dry runs 与 audits，允许读类工具，但默认阻止写、exec、network 和 delegation。
- `SelectiveAutoApprovePermissionService`：适合只自动批准声明过的 selectors 或 risk classes 的脚本化流程。

当这些 presets 太粗时，不要回到 demo-private service，而应升级为组合策略：使用 `PermissionContext(policies=(allow_all_policy(), PermissionPolicy(...)))` 这类 runtime-owned path。

这个目录下的离线 demos 现在统一使用官方 `AllowAllPermissionService`。

## Workflow-level live smoke

这一层复用了同一个 `examples.projects.coding_workflow_demo` 任务、fixture 与成功标准，只是把 scripted helper 换成了内置 live provider route。
它仍停留在 custom host binding 与 builtin replacement 之下。

| Demo | Integration posture | Use this when | Run command | Expected output |
| --- | --- | --- | --- | --- |
| Coding workflow (live) | Workflow-level live smoke | 离线 coding workflow 已通过，现在你想在引入更重 host 集成前，用同一任务和 fixture 验证内置 live provider route。 | `python3 -B -m examples.projects.coding_workflow_demo --live` | 输出 `mode: live`，并显式暴露缺失凭据的 auth failure，而不是悄悄回退到离线。 |

## 更低层的内置 live OpenAI 路径

如果你想做比 workflow-level live smoke 更低层的 provider smoke，可以使用内置 live OpenAI 路径。
它验证的是 Responses transport layer，而不是 coding-workflow fixture 本身。

最小 live 检查：

```bash
export OPENAI_API_KEY=your-key
export OPENAI_MODEL=gpt-4.1-mini
python3 - <<'PY'
import asyncio
import sys
from pathlib import Path

project_root = Path.cwd()
sys.path.insert(0, str(project_root / "packages" / "core" / "src"))
for src_root in sorted((project_root / "packages").glob("**/src")):
    if str(src_root) not in sys.path:
        sys.path.insert(0, str(src_root))

from weavert.runtime_kernel import RuntimeConfig, assemble_runtime

runtime = assemble_runtime(RuntimeConfig.for_headless_live(project_root))
preflight = asyncio.run(runtime.preflight_default_model_route())
if not preflight.ready:
    raise SystemExit(preflight.to_dict())
messages = asyncio.run(runtime.run_prompt("Summarize this repository and use tools when needed."))
print(messages[-1].text)
PY
```

如果你想做稍强一点的 live smoke，请运行：

```bash
python3 packages/toolchain/scripts/openai_responses_live_smoke.py
```

## Advanced live app demos

这些 demos 位于 seam、user-centric、semantic、project 与 workflow-level live-smoke 层之上。
它们是高级 integration samples，不是普通框架用户的默认 getting-started 路径。

| Demo | Integration posture | Use this when | What it validates | Run command | Expected output |
| --- | --- | --- | --- | --- | --- |
| Code assistant | Advanced host-bound app | 你需要 host-owned UX、durable state、approvals、本地 shell commands、响应式 task/job 渲染，或 builtin replacement。 | 一个 host-bound 的 reactive AI coding shell V2，在 app-owned shell 层上组合官方 coding scenario pack 与共享 coding packages。 | `python3 -B -m examples.apps.code_assistant shell` | 启动交互式 coding shell，通过 host 响应式渲染 assistant、task、job 与 workflow 活动。 |

重置、检查和脚本化 smoke 命令：

```bash
python3 -B -m examples.apps.code_assistant reset
python3 -B -m examples.apps.code_assistant inspect
python3 -B -m examples.apps.code_assistant run --deterministic --auto-approve
```

如果你想跑 live provider-backed workflow，请用 `python3 -B -m examples.apps.code_assistant run --session-id live-smoke --auto-approve`。如果你想做不依赖 provider 的 shell smoke，请用 `python3 -B -m examples.apps.code_assistant shell --session-id local-shell --auto-approve`，然后依次执行 `/inspect`、`/tasks`、`/jobs`、`/exit`。

这个高级样例在三条验证路径中都保持了 split ownership model 可见：

- app-owned 的 `code-assistant` shell 层，以及 app 配置的 `bash` replacement
- 官方 `weavert-scenario-coding` package，负责 `coding-planner` / `reviewer` / `verifier` 与核心 coding-loop skills
- 共享的 `weavert-shared-git` 与 `weavert-shared-workspace-intelligence` packages，负责 `git_*` 与 `workspace_*` tool families

确定性 `run --deterministic --auto-approve` smoke 会保留这套 split stack 与 durable artifact layout，同时避免 live 凭据。两条 `run` 模式都会报告稳定的 package-manifest、tool-family、definition-owner、transcript、child-run、task-list 与 workflow-ledger anchors。

如果你想做自动检查，运行 `pytest tests/test_runtime_extension_demos.py`。

## 另见

- `../docs/zh-CN/getting-started/starter-scaffolds.md`
- `../docs/zh-CN/guides/testing-and-observability.md`
- `../docs/zh-CN/maintainers/validation-findings.md`
- `apps/code_assistant/README.zh-CN.md`
