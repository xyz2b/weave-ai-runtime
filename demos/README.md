# Runtime Extension Demos

Run every command from the repository root. The demo modules bootstrap `src/` automatically, so they do not require an editable install.

The shared offline model helper lives in [`demos/_shared/scripted_model.py`](./_shared/scripted_model.py). The agent, skill, and project demos use it so they run without external model credentials.

These demos intentionally stay on stable public extension surfaces:

- definition-level hook authoring uses skill frontmatter `hooks`
- runtime-default and per-session hook registration use `RuntimeConfig(hooks=...)` and `session.register_hook(...)`
- package demos separate manifest admission from activation with `RuntimeConfig.extra_package_manifests` and `RuntimeConfig.requested_packages`
- compatibility-only hook surfaces are intentionally left out of this learning path

Run the seam-basics demos first if you want the minimum runnable extension surfaces. Then run the semantic demos to learn how skill hooks are authored, how default hook registration differs from session-local registration, and how package admission differs from activation.

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
