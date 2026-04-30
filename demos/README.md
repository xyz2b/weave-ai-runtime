# Runtime Extension Demos

Run every command from the repository root. The demo modules bootstrap `src/` automatically, so they do not require an editable install.

The shared offline model helper lives in [`demos/_shared/scripted_model.py`](./_shared/scripted_model.py). The agent, skill, and project demos use it so they run without external model credentials.

There are two distinct demo tracks in this repository:

- the offline seam demos in this README, which use the scripted helper and never hit a live provider
- the bundled live OpenAI path, which uses the runtime default `openai_default` route backed by Responses API

These demos intentionally stay on stable public extension surfaces:

- definition-level hook authoring uses skill frontmatter `hooks`
- runtime-default and per-session hook registration use `RuntimeConfig(hooks=...)` and `session.register_hook(...)`
- package demos separate manifest admission from activation with `RuntimeConfig.extra_package_manifests` and `RuntimeConfig.requested_packages`
- compatibility-only hook surfaces are intentionally left out of this learning path

Run the seam-basics demos first if you want the minimum runnable extension surfaces. Then run the semantic demos to learn how skill hooks are authored, how default hook registration differs from session-local registration, and how package admission differs from activation.

## Offline demos vs live OpenAI path

Everything in the tables below is intentionally offline and deterministic.
If you only want to learn extension seams, stay on this path and do not export any provider credentials.

If you want to exercise the bundled live coding path instead, set:

- `OPENAI_API_KEY` (required)
- `OPENAI_BASE_URL` (optional)
- `OPENAI_MODEL` (optional, defaults to `gpt-4.1-mini`)

Minimal live check from the repo root:

```bash
export OPENAI_API_KEY=your-key
export OPENAI_MODEL=gpt-4.1-mini
python3 - <<'PY'
import asyncio
from pathlib import Path

from weavert.runtime_kernel import RuntimeConfig, assemble_runtime

runtime = assemble_runtime(RuntimeConfig(working_directory=Path.cwd()))
messages = asyncio.run(runtime.run_prompt(\"Summarize this repository and use tools when needed.\"))
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

That script verifies the default full toolset path, checks for multi-tool turns, and reports whether the streaming empty-completed-output fallback had to fire for the current gateway.

Basic troubleshooting:

- missing `OPENAI_API_KEY` -> first invocation returns a structured `auth_error`
- tool schema uses dynamic `additionalProperties` -> invocation returns `tool_schema_error`
- need a proxy or gateway -> set `OPENAI_BASE_URL`
- want a different bundled default model -> set `OPENAI_MODEL`

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

After you understand the individual seams, run the project demo to see the same surfaces composed into one realistic release workflow.

## Project demos

These demos combine multiple stable extension seams into a single project-shaped workflow.
Run them after the seam-basics and semantic demos if you want to see how the pieces behave when they are composed into a small realistic system.

| Demo | What it simulates | Extension seams | Run command | Expected output |
| --- | --- | --- | --- | --- |
| Release workflow | A release-readiness review for a small project workspace | file-backed `tool` + file-backed `agent` + file-backed `skill` + package-contributed context/capability | `python3 -B -m demos.projects.release_workflow_demo` | Prints the discovered workspace facts, the active release-freeze context, a child-generated release summary, and a final release verdict. |

If you want an automated check that these commands still work, run `pytest tests/test_runtime_extension_demos.py`.
