# Runtime Extension Demos

Run every command from the repository root. The demo modules bootstrap `src/` automatically, so they do not require an editable install.

The shared offline model helper lives in [`demos/_shared/scripted_model.py`](./_shared/scripted_model.py). The agent and skill demos use it so they run without external model credentials.

These demos intentionally stay on the current stable extension surfaces:

- hook examples use `session.register_hook(...)` and package-owned contributors
- definition-level hook guidance prefers skill hooks over agent-owned hooks
- package examples use `RuntimeConfig.extra_package_manifests` and `RuntimeConfig.requested_packages`

| Demo | Extension seam | Run command | Expected output |
| --- | --- | --- | --- |
| File-backed tool | `.weavert/tools/*.py` | `python3 -B -m demos.tools.file_backed_tool_demo` | Prints `available tools: report_status` and a deterministic tool result payload. |
| File-backed agent | `.weavert/agents/*.md` | `python3 -B -m demos.agents.file_backed_agent_demo` | Prints `agent: release-reviewer` and a short approval reply from the discovered agent. |
| File-backed skill | `.weavert/skills/**/SKILL.md` | `python3 -B -m demos.skills.file_backed_skill_demo` | Prints `skill: release-summary`, `mode: fork`, and the child-agent reply. |
| Session hook | `session.register_hook(...)` | `python3 -B -m demos.hooks.session_register_hook_demo` | Prints `hook activation: active` and shows the hook-rewritten `echo` tool result. |
| Provider-only package | `build_provider_only_invocation_package_manifest()` | `python3 -B -m demos.packages.provider_only_package_demo` | Prints `visible invocations: package-release-check` and the provider registration metadata. |
| General package contribution | `RuntimePackageManifest` + `PackageContribution` | `python3 -B -m demos.packages.general_package_demo` | Prints the resolved capability payload and the hook-stage context fragment injected by the package. |

If you want an automated check that these commands still work, run `pytest tests/test_runtime_extension_demos.py`.
