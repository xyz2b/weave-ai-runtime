# Scenario Runtime Pack Quickstart

这页给“最终接入方 / 产品开发者”一个直接可抄的 quickstart：如果你只想知道
“这几个 package 到底怎么接进 runtime”，优先看这里。

## 1. 先记住一个 baseline

这些 reference shared/scenario package 都有同一个前提：

- 它们不是默认 distribution baseline 的一部分
- 它们不会自动进入 runtime
- 必须通过 `RuntimeConfig.extra_package_manifests` admission
- 必须通过 `RuntimeConfig.requested_packages` 才会真正激活

也就是说，正确姿势不是“切一个新的 runtime mode”，而是：

1. 先选 `distribution`
2. 再选 `enabled_packages`
3. 再 admission + request 这些 external/optional package
4. 最后由 app 自己决定 provider、store、host、permission policy

## 2. 最小 activation 模板

```python
from pathlib import Path

from weavert.runtime_kernel import RuntimeConfig, assemble_runtime
from weavert.scenario_runtime_packs import reference_scenario_runtime_pack_manifests

runtime = assemble_runtime(
    RuntimeConfig(
        working_directory=Path.cwd(),
        distribution="weavert-core",
        enabled_packages=set(),
        extra_package_manifests=reference_scenario_runtime_pack_manifests(),
        requested_packages=set(),
    )
)
```

后面四种 recipe，主要就是替换：

- `enabled_packages`
- `requested_packages`

## 3. Recipe A: AI coding

适合：

- CLI coding shell
- IDE coding assistant
- repo-oriented coding workflow

推荐组合：

- scenario pack
  - `weavert-scenario-coding`
- recommended first-party packages
  - `weavert-devtools`
  - `weavert-planning`
  - `weavert-builtin-workflows`

```python
from pathlib import Path

from weavert.runtime_kernel import RuntimeConfig, assemble_runtime
from weavert.scenario_runtime_packs import reference_scenario_runtime_pack_manifests

runtime = assemble_runtime(
    RuntimeConfig(
        working_directory=Path.cwd(),
        distribution="weavert-core",
        enabled_packages={
            "weavert-devtools",
            "weavert-planning",
            "weavert-builtin-workflows",
        },
        extra_package_manifests=reference_scenario_runtime_pack_manifests(),
        requested_packages={"weavert-scenario-coding"},
    )
)
```

接入后通常会拿到：

- shared coding tools
  - `git_status`, `git_diff`, `git_history`
  - `workspace_symbols`, `workspace_references`, `workspace_outline`, `workspace_test_targets`
- workflow control primitives
  - `agent`, `skill`, `task_*`, `job_*`
- scenario-pack-owned workflow agents / skills
  - `coding-planner`, `reviewer`, `verifier`
  - `coding-loop`, `review-change`, `verify-change`, `task-discipline`, `repo-onboard`

如果你想看一个完整 app wiring，可以直接参考：

- `examples/apps/code_assistant/app.py`

## 4. Recipe B: AI chat

适合：

- grounded Q&A
- support chat
- citation-aware assistant

推荐组合：

- scenario pack
  - `weavert-scenario-chat`
- recommended first-party packages
  - `weavert-memory`

```python
from pathlib import Path

from weavert.runtime_kernel import RuntimeConfig, assemble_runtime
from weavert.scenario_runtime_packs import reference_scenario_runtime_pack_manifests

runtime = assemble_runtime(
    RuntimeConfig(
        working_directory=Path.cwd(),
        distribution="weavert-core",
        enabled_packages={"weavert-memory"},
        extra_package_manifests=reference_scenario_runtime_pack_manifests(),
        requested_packages={"weavert-scenario-chat"},
    )
)
```

接入后通常会拿到：

- grounding tools
  - `retrieve_context`, `prepare_citations`
  - `grounding_web_search`, `grounding_web_fetch`
- workflow control primitives
  - `ask_user`
- scenario-pack-owned workflow agents / skills
  - `researcher`, `support-agent`, `memory-curator`
  - `chat-summarize`, `answer-with-citations`, `clarify-request`, `capture-preferences`

默认边界是 read-mostly；它不会顺手带进 coding 的 `edit` / `bash` surface。

## 5. Recipe C: Local assistant

适合：

- 桌面工作助手
- 设备侧助理
- host-mediated personal workflow assistant

推荐组合：

- scenario pack
  - `weavert-scenario-local-assistant`
- recommended first-party packages
  - `weavert-memory`

```python
from pathlib import Path

from weavert.runtime_kernel import RuntimeConfig, assemble_runtime
from weavert.scenario_runtime_packs import reference_scenario_runtime_pack_manifests

runtime = assemble_runtime(
    RuntimeConfig(
        working_directory=Path.cwd(),
        distribution="weavert-core",
        enabled_packages={"weavert-memory"},
        extra_package_manifests=reference_scenario_runtime_pack_manifests(),
        requested_packages={"weavert-scenario-local-assistant"},
    )
)
```

接入后通常会拿到：

- retrieval / bridge tools
  - `retrieve_context`, `prepare_citations`
  - `browser_snapshot`, `browser_stage_navigation`, `browser_stage_interaction`
  - `local_os_snapshot`, `local_os_stage_file_change`, `local_os_stage_process_launch`, `local_os_stage_notification`
  - `pim_list_agenda`, `pim_lookup_contacts`, `pim_stage_calendar_event`, `pim_stage_reminder`, `pim_stage_task`
- workflow control primitives
  - `ask_user`, `skill`
- scenario-pack-owned workflow agents / skills
  - `assistant-planner`, `assistant-action-worker`, `assistant-recovery`
  - `safe-action-check`, `daily-brief`, `resume-interrupted-task`, `research-and-act`

这里最重要的不是“能不能看见这些 tool”，而是 host 侧有没有真正绑定 bridge facet。

如果你想让这些 bridge tool 返回 live state 或 host-specific staged receipt，还需要在 app /
host 层绑定 facet，例如：

- `weavert.local_assistant.bridge.browser`
- `weavert.local_assistant.bridge.local_os`
- `weavert.local_assistant.bridge.pim`

如果不绑定：

- 只读 bridge 可能返回 `host_bridge_required`
- staged bridge 会返回 staged request，但不会替你偷偷执行本机动作

## 6. Recipe D: Shared packages only

适合：

- 你已经有自己的 app shell / 主 agent
- 你只想增加某块 reusable capability
- 你不想一起引入完整 scenario workflow

常见组合：

- coding augmentation
  - `weavert-shared-git`
  - `weavert-shared-workspace-intelligence`
- grounded chat augmentation
  - `weavert-shared-retrieval`
  - `weavert-bridge-web`
- local assistant bridge augmentation
  - `weavert-bridge-browser`
  - `weavert-bridge-local-os`
  - `weavert-bridge-pim`

```python
from pathlib import Path

from weavert.runtime_kernel import RuntimeConfig, assemble_runtime
from weavert.scenario_runtime_packs import reference_scenario_runtime_pack_manifests

runtime = assemble_runtime(
    RuntimeConfig(
        working_directory=Path.cwd(),
        distribution="weavert-core",
        extra_package_manifests=reference_scenario_runtime_pack_manifests(),
        requested_packages={
            "weavert-shared-retrieval",
            "weavert-bridge-web",
        },
    )
)
```

这种模式下：

- runtime 只会 materialize 你 request 的 shared capability surface
- 不会额外带入 coding/chat/local assistant 的高层 workflow agents / skills

## 7. 怎么确认 package 真的进来了

推荐先看两条 inspect path。

### 7.1 看 projected manifest metadata

```python
manifests = runtime.services.metadata["package_manifests"]
coding_manifest = manifests["weavert-scenario-coding"]
```

适合看：

- `package_candidate`
- `scenario_profile`
- `expected_tools`
- `workflow_agent_ids`
- `workflow_skill_ids`

### 7.2 看 capability payload

```python
coding_capability = runtime.services.require_capability(
    "weavert.reference.scenario.coding"
)
```

适合看：

- `expected_tools`
- `expected_agents`
- `expected_skills`
- `app_owned_wiring`
- `permission_policy_posture`

## 8. 常见误区

- 只把 manifest 放进 `extra_package_manifests`
  - 这只算 admission，不算 activation；还要 `requested_packages`
- 只 request scenario pack，不开推荐 first-party package
  - scenario-pack-own workflow agents / skills 仍会出现
  - 但很多 generic expected surface 不会自动 materialize
- 以为 local assistant bridge package 会直接接管 OS / browser / PIM
  - 不会；最终 live binding、allowlist、audit sink 都仍然是 app-owned
- 以为这些 package 会进入默认 distribution
  - 不会；它们必须保持 external/optional

## 9. 接下来读什么

- 想看架构边界
  - `docs/weavert-scenario-runtime-pack-architecture.md`
- 想看 package-surface contract / authoring 约定
  - `docs/weavert-user-extension-guide.md`
- 想看 coding 场景完整 app 示例
  - `examples/apps/code_assistant/app.py`
