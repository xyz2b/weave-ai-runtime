# Runtime Extension Demos

Run every command from the repository root. The demo modules bootstrap `src/` automatically, so they do not require an editable install.

The public offline workflow testing kit now lives under `weavert.testing`. The seam, skill, and project demos use that shared runtime-owned surface so the default validation story stays deterministic and does not require external model credentials.

If you are starting a brand-new WeaveRT project, begin with the official starter scaffolds in `docs/weavert-starter-scaffolds.md`. The demos in this folder are the validation story, not the primary copy-paste adoption path.

## Layered validation path

This repository now presents the runnable demos as a layered framework-validation path instead of a flat catalog:

1. `Seam basics` validate one stable extension surface at a time.
2. `User-centric validation` answers the adopter questions that usually come next: guarded tools, scoped delegation, host binding, report ownership, diagnostics, and durable resume.
3. `Semantic demos` validate how those surfaces behave when hooks or packages change the runtime contract.
4. `Project demos` validate realistic workflows that stay on the ordinary extension path through workspace-local definitions and bundled runtime surfaces, without custom host binding or builtin replacement.
5. `Workflow-level live smoke` validates that the same coding workflow and fixture can be exercised against the bundled live provider route before you add heavier integration code.
6. `Advanced live app demos` validate product-style integration seams such as `bind_host()`, durable state, approvals, and builtin replacement.

Recommended starting path:

- If you are an ordinary framework user building a new project, generate a starter scaffold first, then come back here to validate the public seams.
- If you want repo-owned validation after that, start with `Seam basics`, then move into `User-centric validation` so you can answer one adopter question at a time before composing a broader workflow.
- If you want hook- or package-shaped contract changes after that, run the `Semantic demos`.
- Then run `python3 -B -m demos.projects.coding_workflow_demo`.
- If that offline coding workflow passes and you want provider-backed evidence for the same workflow, run `python3 -B -m demos.projects.coding_workflow_demo --live`.
- If you need host-owned UX, durable runtime state, or builtin replacement, move on to the advanced integration sample under `demos/apps/code_assistant/`.

How to interpret failures across the layers:

- seam basics fail -> likely a discovery or stable-seam contract issue
- user-centric validation fail -> likely a tool-authoring, delegation, host-binding, or runtime-helper contract issue that is still isolated to one named seam
- semantic demo fail -> likely a hook or package composition issue that changes the baseline seam contract
- offline coding workflow fail -> likely a framework assembly, workspace-definition, or stable-seam composition issue
- offline pass but workflow-level live smoke fail -> likely a provider credential, prompt, or open-ended model stability issue
- offline and workflow-level live smoke pass but advanced app fail -> likely a host, builtin replacement, or product-integration issue

## Live validation prerequisites

Everything in the seam, user-centric, semantic, and default project tables below is intentionally offline and deterministic.
If you only want to learn the framework surfaces, stay on that path and do not export any provider credentials.

If you want to exercise the live validation layers, set:

- `OPENAI_API_KEY` (required)
- `OPENAI_BASE_URL` (optional)
- `OPENAI_MODEL` (optional, defaults to `gpt-4.1-mini`)

## Seam basics

| Demo | Extension seam | Run command | Expected output |
| --- | --- | --- | --- |
| File-backed tool | `.weavert/tools/*.py` | `python3 -B -m demos.tools.file_backed_tool_demo` | Prints `available tools: report_status` and a deterministic tool result payload. |
| File-backed agent | `.weavert/agents/*.md` | `python3 -B -m demos.agents.file_backed_agent_demo` | Prints `agent: release-reviewer` and a short approval reply from the discovered agent. |
| File-backed skill | `.weavert/skills/**/SKILL.md` | `python3 -B -m demos.skills.file_backed_skill_demo` | Prints `skill: release-summary`, `mode: fork`, and the child-agent reply. |
| Session hook | `session.register_hook(...)` + `weavert.hooks` helper builders | `python3 -B -m demos.hooks.session_register_hook_demo` | Prints `hook activation: active` and shows the hook-rewritten `echo` tool result. |
| Capability-only package | `build_capability_only_package_manifest()` | `python3 -B -m demos.packages.capability_only_package_demo` | Prints the resolved capability payload plus package owner and manifest metadata. |
| Context-contributor-only package | `build_context_contributor_only_package_manifest()` | `python3 -B -m demos.packages.context_contributor_only_package_demo` | Prints the injected hook fragment and the contributor owner metadata. |
| Provider-only package | `build_provider_only_invocation_package_manifest()` | `python3 -B -m demos.packages.provider_only_package_demo` | Prints `visible invocations: package-release-check` and the provider registration metadata. |
| General package contribution | `RuntimePackageManifest` + `PackageContribution` | `python3 -B -m demos.packages.general_package_demo` | Prints the resolved capability payload and the hook-stage context fragment injected by the package. |

## User-centric validation

These demos sit between seam basics and broader workflow samples. They answer focused adopter questions, keep each validation boundary narrow, and pair cleanly with the repo-owned findings ledger at `docs/weavert-demo-validation-findings.md`.

### Focused seam questions

| Demo | Adopter question | Run command | Stable anchors | Why before project demos |
| --- | --- | --- | --- | --- |
| Guarded tool | How do I validate schema errors, permission denial, and a successful guarded tool path before I wire the tool into a larger workflow? | `python3 -B -m demos.tools.guarded_tool_demo` | `demo: guarded tool`, `schema validation: rejected invalid input`, `permission path: denied`, `permission path: allowed`, `status: ok` | It isolates the tool contract before the same behavior is hidden inside a multi-step agent loop. |
| Scoped agent delegation | What actually changes when I delegate to a child agent with a narrower tool pool? | `python3 -B -m demos.agents.scoped_agent_delegation_demo` | `demo: scoped agent delegation`, `visible tools:`, `delegated agent:`, `child summary:`, `status: ok` | It proves tool scoping and child summaries before delegation is mixed into a project workflow. |
| Inline vs fork skill | When should I keep a skill inline versus forking it to a child agent? | `python3 -B -m demos.skills.inline_vs_fork_skill_demo` | `demo: inline vs fork skill`, `inline result:`, `fork child summary:`, `status: ok` | It makes the execution-mode tradeoff visible before skills become one step in a larger composition. |
| Host-registered hook | How do I attach a hook from host-owned integration code and confirm that it actually fired? | `python3 -B -m demos.hooks.host_registered_hook_demo` | `demo: host.register_hook`, `hook source: host`, `dispatch traces:`, `status: ok` | It keeps host-owned hook attachment smaller than a full product shell. |

### Minimal host integration

| Demo | Adopter question | Run command | Stable anchors | Why before advanced app samples |
| --- | --- | --- | --- | --- |
| Minimal host-bound | What is the smallest stable `RuntimeAssembly.bind_host()` path that still shows lifecycle and turn events? | `python3 -B -m demos.hosts.minimal_host_bound_demo` | `demo: minimal host-bound`, `host lifecycle: startup, ready, shutdown`, `turn terminal observed: true`, `status: ok` | It proves the host seam without immediately pulling in approvals, durable state, or builtin replacement. |

### Runtime helper and diagnostics

| Demo | Adopter question | Run command | Stable anchors | Why before project demos or advanced apps |
| --- | --- | --- | --- | --- |
| Stream/report session | Which helper owns the session, and how do I prove a caller-owned session remains reusable? | `python3 -B -m demos.runtime.stream_report_session_demo` | `demo: stream/report session`, `helper-owned report: completed`, `session reusable: true`, `status: ok` | It answers helper-lifecycle questions directly instead of burying them in workflow orchestration. |
| Assembly diagnostics | How do I inspect assembly posture, visible invocations, and a predictable model-route failure without product UX? | `python3 -B -m demos.runtime.assembly_diagnostics_demo` | `demo: assembly diagnostics`, `assembly preset:`, `visible invocations:`, `failure class:`, `status: ok` | It keeps assembly and route diagnostics below host binding and app-specific presentation. |
| Durable resume | What does the minimum durable transcript and resume proof look like before I build custom product UX around it? | `python3 -B -m demos.runtime.durable_resume_demo` | `demo: durable resume`, `turn one persisted: true`, `session resumed: true`, `status: ok` | It validates persistence expectations directly, without requiring the advanced app shell. |

## Semantic demos

| Demo | Extension seam | Run command | Expected output |
| --- | --- | --- | --- |
| Inline skill hooks | skill frontmatter `hooks` + `context: inline` | `python3 -B -m demos.skills.inline_skill_hook_demo` | Prints `first turn result: rewritten` and `second turn result: original`, so you can see the hook travel with the skill and then release. |
| Runtime config hook | `RuntimeConfig(hooks=...)` | `python3 -B -m demos.hooks.runtime_config_hook_demo` | Prints `hook source: runtime_config` plus matching results in two sessions, showing the hook is attached by default instead of registered per session. |
| Package activation | `RuntimeConfig.extra_package_manifests` vs `RuntimeConfig.requested_packages` | `python3 -B -m demos.packages.package_activation_demo` | Prints an admitted-but-inactive package with no visible invocations, then the same package activated with `package-release-check` visible. |

After you validate the focused user-centric layer and any semantic variations you care about, move into the project layer to see the same public surfaces composed into realistic workflows.

## Project demos

These demos stay on the ordinary extension path. They use workspace-local `.weavert/` definitions plus bundled runtime surfaces, and they do not require custom host binding or builtin replacements.

| Demo | What it validates | Run command | Expected output |
| --- | --- | --- | --- |
| Release workflow | A composed offline release-readiness review for a small project workspace | `python3 -B -m demos.projects.release_workflow_demo` | Prints the discovered workspace facts, the active release-freeze context, a child-generated release summary, and a final release verdict. |
| Coding workflow | A bugfix-style inspect -> edit -> verify -> review loop in a tiny workspace, still below host customization and builtin replacement | `python3 -B -m demos.projects.coding_workflow_demo` | Prints `mode: offline`, `host customization: none`, `builtin replacements: none`, `verification: passed`, `review: pass`, and `status: ok`. |

## Headless permission presets

When you move from interactive demos to CI, smoke, or scripted runs, prefer the runtime-owned permission presets instead of handwritten stubs:

- `AllowAllPermissionService`: fast smoke coverage where the fixture is already sandboxed and you want zero host prompts.
- `DenyAllPermissionService`: strict CI or harness validation where any unexpected tool, skill, or child-agent permission request should fail closed.
- `ReadOnlyPermissionService`: inspect-only workflows, dry runs, and audits that should allow read-classified tools but block writes, exec, network, and delegation by default.
- `SelectiveAutoApprovePermissionService`: scripted workflows that should auto-approve only declared selectors or risk classes and deterministically deny or bubble unmatched requests.

When a preset becomes too coarse, keep the same runtime-owned path and move one step up to composed policies: build a `PermissionContext(policies=(allow_all_policy(), PermissionPolicy(...)))` stack instead of swapping to a demo-private permission service. That preserves the same shared control-plane behavior for tools, skills, and delegated agents while giving you scope-aware or risk-aware overrides.

The offline demos in this folder now use the official `AllowAllPermissionService` surface instead of a demo-private stub.

## Workflow-level live smoke

This layer reuses the same `demos.projects.coding_workflow_demo` task, fixture, and success criteria, but switches from the scripted helper to the bundled live provider route.
It still stays below custom host binding and builtin replacement.

Run the live smoke path with:

```bash
python3 -B -m demos.projects.coding_workflow_demo --live
```

Expected behavior:

- success still means the same coding workflow completed against the same fixture
- `mode: live` makes the escalation step explicit
- `host customization: none` and `builtin replacements: none` stay visible in the output
- missing credentials surface a clear auth error and the demo does not silently fall back to offline execution

## Lower-level bundled live OpenAI path

If you only want the lower-level provider smoke instead of the workflow-level live smoke above, use the bundled live OpenAI path below.
This validates the Responses transport layer, not the coding-workflow fixture itself.
The snippet starts from the official `for_headless_live(...)` preset so the live route choice is explicit before assembly.

Minimal live check from the repo root:

```bash
export OPENAI_API_KEY=your-key
export OPENAI_MODEL=gpt-4.1-mini
python3 - <<'PY'
import asyncio
from pathlib import Path

from weavert.runtime_kernel import RuntimeConfig, assemble_runtime

runtime = assemble_runtime(RuntimeConfig.for_headless_live(Path.cwd()))
preflight = asyncio.run(runtime.preflight_default_model_route())
if not preflight.ready:
    raise SystemExit(preflight.to_dict())
messages = asyncio.run(runtime.run_prompt("Summarize this repository and use tools when needed."))
print(messages[-1].text)
PY
```

Expected live behavior:

- the default route is still `openai_default`
- requests go through the bundled Responses adapter
- runtime tools are exported as strict function tools
- local tool results are replayed as `function_call_output`
- bundled `openai_default` requests provider-side `parallel_tool_calls=true`
- runtime still owns ordered local continuation and can reconcile empty streaming `response.completed.output` payloads from imperfect gateways

If you want a slightly stronger live smoke than the inline snippet above, run:

```bash
python3 scripts/openai_responses_live_smoke.py
```

Basic troubleshooting:

- missing `OPENAI_API_KEY` -> preflight returns `missing_env`; if you skip preflight, the first invocation still returns `auth_error`
- tool schema uses dynamic `additionalProperties` -> invocation returns `tool_schema_error`
- need a proxy or gateway -> set `OPENAI_BASE_URL`
- want a different bundled default model -> set `OPENAI_MODEL`

## Advanced live app demos

These demos sit above the seam, user-centric, semantic, project, and workflow-level live-smoke layers.
They are advanced integration samples, not the baseline getting-started path for ordinary framework users.

| Demo | What it validates | Run command | Expected output |
| --- | --- | --- | --- |
| Code assistant | Host-bound reactive AI coding shell V2 with local commands, session-oriented `bash`, reusable child agents and skills, durable state, approvals, and builtin replacement for `bash` | `python3 -B -m demos.apps.code_assistant shell` | Starts an interactive coding shell, reactively renders assistant, task, job, and workflow activity through the host, supports `/tasks`, `/jobs`, and `/inspect`, and leaves transcripts plus other durable state under `demos/apps/code_assistant/state/mini_repo/.weavert/`. |

Reset, inspect, and scripted smoke commands for the same advanced integration sample:

```bash
python3 -B -m demos.apps.code_assistant reset
python3 -B -m demos.apps.code_assistant inspect
python3 -B -m demos.apps.code_assistant run --auto-approve
```

That `run --auto-approve` smoke treats missing planning, inspection, verification, or review coverage as blocking `workflow gaps`, while surfacing planner degradation that still left a usable shared plan as non-blocking `workflow advisories`.

If you want an automated check that these commands still work, run `pytest tests/test_runtime_extension_demos.py`.
