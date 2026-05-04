# Runtime Extension Demos

Run every command from the repository root. The demo modules bootstrap `src/` automatically, so they do not require an editable install.

The shared offline model helper lives in [`demos/_shared/scripted_model.py`](./_shared/scripted_model.py). The seam, skill, and project demos use it so the default validation story stays deterministic and does not require external model credentials.

## Layered validation path

This repository now presents the runnable demos as a layered framework-validation path instead of a flat catalog:

1. `Seam basics` validate one stable extension surface at a time.
2. `Semantic demos` validate how those surfaces behave when hooks or packages change the runtime contract.
3. `Project demos` validate realistic workflows that stay on the ordinary extension path through workspace-local definitions and bundled runtime surfaces, without custom host binding or builtin replacement.
4. `Workflow-level live smoke` validates that the same coding workflow and fixture can be exercised against the bundled live provider route before you add heavier integration code.
5. `Advanced live app demos` validate product-style integration seams such as `bind_host()`, durable state, approvals, and builtin replacement.

Recommended starting path:

- If you are an ordinary framework user, start with `Seam basics`, then run `python3 -B -m demos.projects.coding_workflow_demo`.
- If that offline coding workflow passes and you want provider-backed evidence for the same workflow, run `python3 -B -m demos.projects.coding_workflow_demo --live`.
- If you need host-owned UX, durable runtime state, or builtin replacement, move on to the advanced integration sample under `demos/apps/code_assistant/`.

How to interpret failures across the layers:

- offline coding workflow fail -> likely a framework assembly, workspace-definition, or stable-seam composition issue
- offline pass but workflow-level live smoke fail -> likely a provider credential, prompt, or open-ended model stability issue
- offline and workflow-level live smoke pass but advanced app fail -> likely a host, builtin replacement, or product-integration issue

## Live validation prerequisites

Everything in the seam, semantic, and default project tables below is intentionally offline and deterministic.
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
| Session hook | `session.register_hook(...)` | `python3 -B -m demos.hooks.session_register_hook_demo` | Prints `hook activation: active` and shows the hook-rewritten `echo` tool result. |
| Provider-only package | `build_provider_only_invocation_package_manifest()` | `python3 -B -m demos.packages.provider_only_package_demo` | Prints `visible invocations: package-release-check` and the provider registration metadata. |
| General package contribution | `RuntimePackageManifest` + `PackageContribution` | `python3 -B -m demos.packages.general_package_demo` | Prints the resolved capability payload and the hook-stage context fragment injected by the package. |

## Semantic demos

| Demo | Extension seam | Run command | Expected output |
| --- | --- | --- | --- |
| Inline skill hooks | skill frontmatter `hooks` + `context: inline` | `python3 -B -m demos.skills.inline_skill_hook_demo` | Prints `first turn result: rewritten` and `second turn result: original`, so you can see the hook travel with the skill and then release. |
| Runtime config hook | `RuntimeConfig(hooks=...)` | `python3 -B -m demos.hooks.runtime_config_hook_demo` | Prints `hook source: runtime_config` plus matching results in two sessions, showing the hook is attached by default instead of registered per session. |
| Package activation | `RuntimeConfig.extra_package_manifests` vs `RuntimeConfig.requested_packages` | `python3 -B -m demos.packages.package_activation_demo` | Prints an admitted-but-inactive package with no visible invocations, then the same package activated with `package-release-check` visible. |

After you understand the individual seams, move into the project layer to see the same public surfaces composed into realistic workflows.

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

These demos sit above the seam, semantic, project, and workflow-level live-smoke layers.
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
