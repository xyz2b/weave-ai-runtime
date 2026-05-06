from __future__ import annotations

import argparse
from dataclasses import dataclass
from enum import StrEnum
import json
from pathlib import Path
from pathlib import PurePosixPath
import re
from textwrap import dedent

from .public_contract import CANONICAL_WORKSPACE_ROOT
from .runtime_kernel import RuntimeAssemblyPresetName


def _require_relative_file(value: str, field_name: str) -> str:
    candidate = str(value).strip()
    if not candidate:
        raise ValueError(f"{field_name} must not be empty")
    path = Path(candidate)
    if path.is_absolute() or path.name != candidate:
        raise ValueError(f"{field_name} must be a simple relative file name")
    return candidate


class StarterScaffoldName(StrEnum):
    MINIMAL_PROJECT = "minimal-project"
    HEADLESS_WORKFLOW = "headless-workflow"
    LIVE_SMOKE = "live-smoke"


@dataclass(frozen=True, slots=True)
class StarterScaffoldDefinition:
    name: StarterScaffoldName | str
    summary: str
    entrypoint: str
    assembly_preset: RuntimeAssemblyPresetName | str
    execution_mode: str
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", StarterScaffoldName(self.name))
        object.__setattr__(self, "summary", str(self.summary).strip())
        object.__setattr__(self, "entrypoint", _require_relative_file(self.entrypoint, "entrypoint"))
        object.__setattr__(self, "assembly_preset", RuntimeAssemblyPresetName(self.assembly_preset))
        object.__setattr__(self, "execution_mode", str(self.execution_mode).strip())
        object.__setattr__(self, "notes", tuple(str(note).strip() for note in self.notes if str(note).strip()))


@dataclass(frozen=True, slots=True)
class StarterScaffoldGenerationResult:
    definition: StarterScaffoldDefinition
    destination: Path
    project_name: str
    written_files: tuple[Path, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "destination", Path(self.destination).resolve())
        object.__setattr__(self, "project_name", str(self.project_name).strip())
        object.__setattr__(self, "written_files", tuple(Path(path).resolve() for path in self.written_files))

    @property
    def entrypoint_path(self) -> Path:
        return self.destination / self.definition.entrypoint


@dataclass(frozen=True, slots=True)
class _TemplateContext:
    definition: StarterScaffoldDefinition
    destination: Path
    project_name: str
    project_slug: str

    @property
    def preset_name(self) -> str:
        return self.definition.assembly_preset.value


_STARTER_MANIFEST_PATH = f"{CANONICAL_WORKSPACE_ROOT}/starter-scaffold-manifest.json"
_LEGACY_GENERATED_FILE_CANDIDATES = (
    ".weavert/agents/starter-guide.md",
    ".weavert/agents/release-runner.md",
    ".weavert/agents/live-smoke-runner.md",
    ".weavert/tools/project_snapshot.py",
    ".weavert/tools/workflow_checklist.py",
    ".weavert/tools/.gitkeep",
    "app.py",
    "workflow_runner.py",
    "live_smoke.py",
)


_OFFICIAL_STARTER_SCAFFOLDS: dict[str, StarterScaffoldDefinition] = {
    StarterScaffoldName.MINIMAL_PROJECT.value: StarterScaffoldDefinition(
        name=StarterScaffoldName.MINIMAL_PROJECT,
        summary="Small runnable offline baseline with project-local agent and tool extension points.",
        entrypoint="app.py",
        assembly_preset=RuntimeAssemblyPresetName.ORDINARY_WORKFLOW,
        execution_mode="offline-scripted",
        notes=(
            "Uses the ordinary workflow preset and canonical .weavert workspace layout.",
            "Keeps the first run deterministic by using the public weavert.testing helpers.",
        ),
    ),
    StarterScaffoldName.HEADLESS_WORKFLOW.value: StarterScaffoldDefinition(
        name=StarterScaffoldName.HEADLESS_WORKFLOW,
        summary="Runnable headless workflow baseline built around the public workflow report helpers.",
        entrypoint="workflow_runner.py",
        assembly_preset=RuntimeAssemblyPresetName.ORDINARY_WORKFLOW,
        execution_mode="headless-report",
        notes=(
            "Uses run_workflow_test() plus result projection helpers instead of manual session glue.",
            "Keeps the baseline deterministic while leaving a clear path to project-specific tools and agents.",
        ),
    ),
    StarterScaffoldName.LIVE_SMOKE.value: StarterScaffoldDefinition(
        name=StarterScaffoldName.LIVE_SMOKE,
        summary="Explicit live-provider smoke path with runtime-owned preflight and no offline fallback.",
        entrypoint="live_smoke.py",
        assembly_preset=RuntimeAssemblyPresetName.HEADLESS_LIVE,
        execution_mode="live-preflight",
        notes=(
            "Uses the headless live preset so the bundled provider route is explicit before execution.",
            "Blocks on preflight failures instead of silently swapping to a scripted or offline path.",
        ),
    ),
}


def official_starter_scaffold_catalog() -> dict[str, StarterScaffoldDefinition]:
    return dict(_OFFICIAL_STARTER_SCAFFOLDS)


def official_starter_scaffold(name: StarterScaffoldName | str) -> StarterScaffoldDefinition:
    return _OFFICIAL_STARTER_SCAFFOLDS[StarterScaffoldName(name).value]


def generate_starter_scaffold(
    shape: StarterScaffoldName | str,
    destination: Path | str,
    *,
    project_name: str | None = None,
    force: bool = False,
) -> StarterScaffoldGenerationResult:
    definition = official_starter_scaffold(shape)
    resolved_destination = Path(destination).resolve()
    resolved_name = _resolve_project_name(resolved_destination, project_name)
    context = _TemplateContext(
        definition=definition,
        destination=resolved_destination,
        project_name=resolved_name,
        project_slug=_normalize_project_slug(resolved_name),
    )
    files = _render_scaffold_files(context)
    files[_STARTER_MANIFEST_PATH] = _render_starter_manifest(
        definition=definition,
        project_name=resolved_name,
        generated_files=tuple(sorted((*files.keys(), _STARTER_MANIFEST_PATH))),
    )
    _prepare_destination(resolved_destination, force=force)
    written_files = _write_scaffold_files(context, files)
    return StarterScaffoldGenerationResult(
        definition=definition,
        destination=resolved_destination,
        project_name=resolved_name,
        written_files=written_files,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="weavert-starter",
        description="Generate official WeaveRT starter scaffolds.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="Show the official starter scaffold catalog.")
    list_parser.set_defaults(handler=_handle_list)

    generate_parser = subparsers.add_parser("generate", help="Generate one official starter scaffold.")
    generate_parser.add_argument(
        "shape",
        choices=tuple(_OFFICIAL_STARTER_SCAFFOLDS),
        help="Starter scaffold shape to generate.",
    )
    generate_parser.add_argument("destination", help="Target directory for the generated scaffold.")
    generate_parser.add_argument(
        "--project-name",
        help="Optional display name to use inside the generated scaffold.",
    )
    generate_parser.add_argument(
        "--force",
        action="store_true",
        help="Allow writing into an existing non-empty directory by replacing files from a previous scaffold generation.",
    )
    generate_parser.set_defaults(handler=_handle_generate)

    args = parser.parse_args(argv)
    return int(args.handler(args))


def _handle_list(args: argparse.Namespace) -> int:
    _ = args
    for definition in official_starter_scaffold_catalog().values():
        print(f"{definition.name.value}: {definition.summary}")
        print(f"  preset: {definition.assembly_preset.value}")
        print(f"  entrypoint: {definition.entrypoint}")
    return 0


def _handle_generate(args: argparse.Namespace) -> int:
    result = generate_starter_scaffold(
        args.shape,
        args.destination,
        project_name=args.project_name,
        force=bool(args.force),
    )
    print(f"generated {result.definition.name.value} at {result.destination}")
    print(f"entrypoint: {result.entrypoint_path}")
    return 0


def _prepare_destination(destination: Path, *, force: bool) -> None:
    if destination.exists() and destination.is_file():
        raise NotADirectoryError(destination)
    if destination.exists() and any(destination.iterdir()) and not force:
        raise FileExistsError(
            f"Destination '{destination}' is not empty. Pass force=True or use --force to replace scaffold files."
        )
    destination.mkdir(parents=True, exist_ok=True)
    if force:
        _remove_previous_generated_files(destination)


def _write_scaffold_files(
    context: _TemplateContext,
    files: dict[str, str],
) -> tuple[Path, ...]:
    written: list[Path] = []
    for relative_path, contents in sorted(files.items()):
        target = context.destination / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(contents, encoding="utf-8")
        written.append(target)
    return tuple(written)


def _render_scaffold_files(context: _TemplateContext) -> dict[str, str]:
    renderer = {
        StarterScaffoldName.MINIMAL_PROJECT: _render_minimal_project,
        StarterScaffoldName.HEADLESS_WORKFLOW: _render_headless_workflow,
        StarterScaffoldName.LIVE_SMOKE: _render_live_smoke,
    }[context.definition.name]
    return renderer(context)


def _render_starter_manifest(
    *,
    definition: StarterScaffoldDefinition,
    project_name: str,
    generated_files: tuple[str, ...],
) -> str:
    return json.dumps(
        {
            "version": 1,
            "shape": definition.name.value,
            "project_name": project_name,
            "generated_files": list(generated_files),
        },
        indent=2,
        sort_keys=True,
    ) + "\n"


def _remove_previous_generated_files(destination: Path) -> None:
    manifest_path = destination / _STARTER_MANIFEST_PATH
    if not manifest_path.exists():
        _remove_legacy_generated_files(destination)
        return
    generated_files = _load_generated_file_manifest(manifest_path)
    for relative_path in sorted(generated_files, key=lambda value: len(PurePosixPath(value).parts), reverse=True):
        target = _resolved_destination_path(destination, relative_path)
        if target.is_file():
            target.unlink()
        _prune_empty_parent_directories(target.parent, stop_at=destination)


def _remove_legacy_generated_files(destination: Path) -> None:
    for relative_path in sorted(_LEGACY_GENERATED_FILE_CANDIDATES, key=lambda value: len(PurePosixPath(value).parts), reverse=True):
        target = _resolved_destination_path(destination, relative_path)
        if target.is_file():
            target.unlink()
        _prune_empty_parent_directories(target.parent, stop_at=destination)


def _load_generated_file_manifest(manifest_path: Path) -> tuple[str, ...]:
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Starter scaffold manifest at '{manifest_path}' is not valid JSON.") from exc
    generated_files = payload.get("generated_files")
    if not isinstance(generated_files, list):
        raise ValueError(f"Starter scaffold manifest at '{manifest_path}' does not publish a generated_files list.")
    return tuple(_normalize_manifest_relative_path(value) for value in generated_files)


def _normalize_manifest_relative_path(value: object) -> str:
    candidate = str(value).strip()
    if not candidate:
        raise ValueError("starter scaffold manifest paths must not be empty")
    path = PurePosixPath(candidate)
    if path.is_absolute() or ".." in path.parts or path.name in {"", ".", ".."}:
        raise ValueError(f"starter scaffold manifest path must stay within the project root: {candidate!r}")
    return path.as_posix()


def _resolved_destination_path(destination: Path, relative_path: str) -> Path:
    target = (destination / Path(relative_path)).resolve()
    if not target.is_relative_to(destination):
        raise ValueError(f"starter scaffold manifest path escapes destination root: {relative_path!r}")
    return target


def _prune_empty_parent_directories(directory: Path, *, stop_at: Path) -> None:
    current = directory
    while current != stop_at and current.is_dir():
        try:
            current.rmdir()
        except OSError:
            break
        current = current.parent



def _render_minimal_project(context: _TemplateContext) -> dict[str, str]:
    assistant_text = (
        "The scaffold is ready. Keep new project definitions under .weavert/ and extend this baseline one tool, agent, or skill at a time."
    )
    return {
        ".gitignore": _common_gitignore(),
        "README.md": _minimal_readme(context),
        "app.py": _python(
            f'''
            from __future__ import annotations

            import asyncio
            from pathlib import Path

            from weavert import (
                AllowAllPermissionService,
                RuntimeConfig,
                assemble_runtime,
                final_assistant_text,
                latest_tool_outcome,
            )
            from weavert.testing import ScriptedModelClient, text_batch, tool_call_batch


            def build_model_client() -> ScriptedModelClient:
                return ScriptedModelClient(
                    [
                        tool_call_batch(
                            request_id="req-minimal-1",
                            tool_name="project_snapshot",
                            tool_input={{}},
                            call_id="call-project-snapshot",
                        ),
                        text_batch(
                            request_id="req-minimal-2",
                            text={assistant_text!r},
                        ),
                    ]
                )


            async def run() -> None:
                project_root = Path(__file__).resolve().parent
                config = RuntimeConfig.for_ordinary_workflow(project_root)
                config.model_client = build_model_client()
                runtime = assemble_runtime(config)
                runtime.services.permissions = AllowAllPermissionService()

                # Add more project-local definitions under .weavert/ as this project grows.
                report = await runtime.run_prompt_report(
                    "Inspect this starter project and explain the next extension point.",
                    session_id="minimal-project-starter",
                    agent_name="starter-guide",
                    cwd=project_root,
                )

                snapshot = latest_tool_outcome(report, "project_snapshot")
                print(f"preset: {{config.assembly_preset_metadata()['name']}}")
                if snapshot is not None and isinstance(snapshot.output, dict):
                    print(f"workspace root: {{snapshot.output['workspace_root']}}")
                print(f"assistant: {{final_assistant_text(report)}}")
                print("status: ok")


            if __name__ == "__main__":
                asyncio.run(run())
            '''
        ),
        ".weavert/agents/starter-guide.md": dedent(
            '''
            ---
            name: starter-guide
            description: Inspect the starter project snapshot and explain where to extend it next.
            tools:
              - project_snapshot
            ---
            You are the guide for this minimal WeaveRT starter project.

            Workflow:
            1. Call `project_snapshot` before you answer.
            2. Summarize what is already wired in.
            3. End with one short suggestion for the next extension point.
            '''
        ).lstrip(),
        ".weavert/skills/.gitkeep": "",
        ".weavert/tools/project_snapshot.py": _python(
            f'''
            from __future__ import annotations

            from weavert import ToolDefinition, ToolTraits


            def execute(_tool_input, _context):
                return {{
                    "project": {context.project_name!r},
                    "workspace_root": {CANONICAL_WORKSPACE_ROOT!r},
                    "extension_points": [
                        ".weavert/tools",
                        ".weavert/agents",
                        ".weavert/skills",
                    ],
                }}


            TOOL_DEFINITION = ToolDefinition(
                name="project_snapshot",
                description="Describe the starter project's canonical runtime extension points.",
                input_schema={{
                    "type": "object",
                    "properties": {{}},
                    "additionalProperties": False,
                }},
                traits=ToolTraits(read_only=True, concurrency_safe=True),
                execute=execute,
            )
            '''
        ),
        "pyproject.toml": _common_pyproject(
            context,
            "Official WeaveRT minimal project starter scaffold.",
        ),
    }



def _render_headless_workflow(context: _TemplateContext) -> dict[str, str]:
    assistant_text = (
        "Release checklist reviewed. The headless path already returns a workflow report; next add project-specific tools or skills."
    )
    return {
        ".gitignore": _common_gitignore(),
        "README.md": _headless_readme(context),
        "workflow_runner.py": _python(
            f'''
            from __future__ import annotations

            import asyncio
            from pathlib import Path

            from weavert import RuntimeConfig, final_assistant_text, latest_tool_outcome, terminal_failure
            from weavert.testing import ScriptedModelClient, run_workflow_test, text_batch, tool_call_batch


            def build_model_client() -> ScriptedModelClient:
                return ScriptedModelClient(
                    [
                        tool_call_batch(
                            request_id="req-headless-1",
                            tool_name="workflow_checklist",
                            tool_input={{}},
                            call_id="call-workflow-checklist",
                        ),
                        text_batch(
                            request_id="req-headless-2",
                            text={assistant_text!r},
                        ),
                    ]
                )


            async def run() -> int:
                project_root = Path(__file__).resolve().parent
                config = RuntimeConfig.for_ordinary_workflow(project_root)
                report = await run_workflow_test(
                    "Review the current workflow checklist and summarize the next step.",
                    workspace=project_root,
                    runtime_config=config,
                    model_client=build_model_client(),
                    session_id="headless-workflow-starter",
                    agent_name="release-runner",
                )

                failure = terminal_failure(report)
                if failure is not None:
                    print(f"failure: {{failure.failure_class or failure.stop_reason or 'unknown'}}")
                    return 1

                checklist = latest_tool_outcome(report, "workflow_checklist")
                print(f"preset: {{config.assembly_preset_metadata()['name']}}")
                if checklist is not None and isinstance(checklist.output, dict):
                    ready_checks = checklist.output.get("ready_checks", ())
                    print(f"ready checks: {{', '.join(str(item) for item in ready_checks)}}")
                    print(f"next step: {{checklist.output.get('next_step', '')}}")
                print(f"assistant: {{final_assistant_text(report)}}")
                print("status: ok")
                return 0


            if __name__ == "__main__":
                raise SystemExit(asyncio.run(run()))
            '''
        ),
        ".weavert/agents/release-runner.md": dedent(
            '''
            ---
            name: release-runner
            description: Run the headless checklist review and summarize the current workflow status.
            tools:
              - workflow_checklist
            ---
            You are the headless workflow runner for this starter project.

            Workflow:
            1. Call `workflow_checklist` before you answer.
            2. Summarize which checks are already ready.
            3. Mention the next project-specific capability to add.
            '''
        ).lstrip(),
        ".weavert/skills/.gitkeep": "",
        ".weavert/tools/workflow_checklist.py": _python(
            f'''
            from __future__ import annotations

            from weavert import ToolDefinition, ToolTraits


            def execute(_tool_input, _context):
                return {{
                    "project": {context.project_name!r},
                    "workspace_root": {CANONICAL_WORKSPACE_ROOT!r},
                    "ready_checks": [
                        "canonical weavert imports",
                        "project-local agent discovery",
                        "report-oriented workflow execution",
                    ],
                    "next_step": "Add the project-specific tool, skill, or agent that drives your real workflow.",
                }}


            TOOL_DEFINITION = ToolDefinition(
                name="workflow_checklist",
                description="Return the starter workflow checklist for headless runs.",
                input_schema={{
                    "type": "object",
                    "properties": {{}},
                    "additionalProperties": False,
                }},
                traits=ToolTraits(read_only=True, concurrency_safe=True),
                execute=execute,
            )
            '''
        ),
        "pyproject.toml": _common_pyproject(
            context,
            "Official WeaveRT headless workflow starter scaffold.",
        ),
    }



def _render_live_smoke(context: _TemplateContext) -> dict[str, str]:
    return {
        ".gitignore": _common_gitignore(),
        "README.md": _live_readme(context),
        "live_smoke.py": _python(
            '''
            from __future__ import annotations

            import asyncio
            import json
            from pathlib import Path

            from weavert import RuntimeConfig, assemble_runtime, final_assistant_text, terminal_failure


            async def run() -> int:
                project_root = Path(__file__).resolve().parent
                config = RuntimeConfig.for_headless_live(project_root)
                runtime = assemble_runtime(config)

                preflight = await runtime.preflight_default_model_route()
                print(f"preset: {config.assembly_preset_metadata()['name']}")
                print(f"route: {config.default_model_route}")
                if not preflight.ready:
                    print("live route preflight failed; fix the reported requirements before running the smoke path again.")
                    print(json.dumps(preflight.to_dict(), indent=2, sort_keys=True))
                    return 1

                report = await runtime.run_prompt_report(
                    "Reply with a short live smoke confirmation for this starter project.",
                    session_id="live-smoke-starter",
                    agent_name="live-smoke-runner",
                    cwd=project_root,
                )
                failure = terminal_failure(report)
                if failure is not None:
                    print("live workflow failed after preflight.")
                    print(
                        json.dumps(
                            {
                                "stop_reason": failure.stop_reason,
                                "error": failure.error,
                                "failure_class": failure.failure_class,
                                "metadata": dict(failure.metadata),
                            },
                            indent=2,
                            sort_keys=True,
                        )
                    )
                    return 1

                assistant = final_assistant_text(report) or "<empty assistant reply>"
                print(f"assistant: {assistant}")
                print("status: ok")
                return 0


            if __name__ == "__main__":
                raise SystemExit(asyncio.run(run()))
            '''
        ),
        ".weavert/agents/live-smoke-runner.md": dedent(
            '''
            ---
            name: live-smoke-runner
            description: Confirm that the live model route can answer a simple starter-project prompt.
            ---
            You are the live smoke runner for this starter project.

            Reply with a short confirmation that the live route is active and mention one next step for real project logic.
            '''
        ).lstrip(),
        ".weavert/skills/.gitkeep": "",
        ".weavert/tools/.gitkeep": "",
        "pyproject.toml": _common_pyproject(
            context,
            "Official WeaveRT live smoke starter scaffold.",
        ),
    }



def _common_gitignore() -> str:
    return _python(
        '''
        __pycache__/
        *.py[cod]
        .pytest_cache/
        .venv/
        '''
    )



def _common_pyproject(context: _TemplateContext, description: str) -> str:
    return _python(
        f'''
        [build-system]
        requires = ["setuptools>=69", "wheel"]
        build-backend = "setuptools.build_meta"

        [project]
        name = {context.project_slug!r}
        version = "0.1.0"
        description = {description!r}
        requires-python = ">=3.11"
        dependencies = ["weavert"]

        [tool.setuptools]
        py-modules = []
        '''
    )



def _minimal_readme(context: _TemplateContext) -> str:
    return dedent(
        f'''
        # {context.project_name}

        This project was generated from the official WeaveRT `minimal-project` starter scaffold.

        What this scaffold shows:

        - `RuntimeConfig.for_ordinary_workflow(...)` as the baseline assembly preset
        - project-local `{CANONICAL_WORKSPACE_ROOT}/` definitions for agents and tools
        - an offline `ScriptedModelClient` path so the first run does not need provider credentials
        - one small runnable entrypoint you can extend as the project grows

        Quick start:

        This scaffold expects `weavert` to be installed in the same environment that runs the entrypoint.

        1. `python3 -m venv .venv`
        2. `source .venv/bin/activate`
        3. `python -m pip install -e /path/to/weave-ai-runtime/packages/core`
        4. `python -m pip install -e .`
        5. `python app.py`

        If you are using a published `weavert` package instead of a source checkout, install that package in step 3.

        Extension points:

        - add project-local tools under `{CANONICAL_WORKSPACE_ROOT}/tools/`
        - add project-local agents under `{CANONICAL_WORKSPACE_ROOT}/agents/`
        - add project-local skills under `{CANONICAL_WORKSPACE_ROOT}/skills/`
        - replace the scripted batches in `app.py` with a live route when you are ready for provider-backed runs
        '''
    ).lstrip()



def _headless_readme(context: _TemplateContext) -> str:
    return dedent(
        f'''
        # {context.project_name}

        This project was generated from the official WeaveRT `headless-workflow` starter scaffold.

        What this scaffold shows:

        - `RuntimeConfig.for_ordinary_workflow(...)` as the matching official assembly preset
        - `run_workflow_test(...)` as the public headless execution helper
        - `final_assistant_text(...)`, `latest_tool_outcome(...)`, and `terminal_failure(...)` as the report-oriented inspection path
        - project-local `{CANONICAL_WORKSPACE_ROOT}/` definitions as the place to grow your real workflow

        Quick start:

        This scaffold expects `weavert` to be installed in the same environment that runs the entrypoint.

        1. `python3 -m venv .venv`
        2. `source .venv/bin/activate`
        3. `python -m pip install -e /path/to/weave-ai-runtime/packages/core`
        4. `python -m pip install -e .`
        5. `python workflow_runner.py`

        If you are using a published `weavert` package instead of a source checkout, install that package in step 3.

        Extension points:

        - add workflow-specific tools under `{CANONICAL_WORKSPACE_ROOT}/tools/`
        - add more agents or skills under `{CANONICAL_WORKSPACE_ROOT}/agents/` and `{CANONICAL_WORKSPACE_ROOT}/skills/`
        - swap the scripted batches for a project-specific live or test harness once your workflow contract is stable
        '''
    ).lstrip()



def _live_readme(context: _TemplateContext) -> str:
    return dedent(
        f'''
        # {context.project_name}

        This project was generated from the official WeaveRT `live-smoke` starter scaffold.

        What this scaffold shows:

        - `RuntimeConfig.for_headless_live(...)` as the matching official live assembly preset
        - `preflight_default_model_route()` before workflow execution
        - no scripted or offline fallback hidden behind the live entrypoint
        - project-local `{CANONICAL_WORKSPACE_ROOT}/agents/` as the first place to customize live behavior

        Required environment:

        - `OPENAI_API_KEY` (required)
        - `OPENAI_MODEL` (optional)
        - `OPENAI_BASE_URL` (optional)

        Quick start:

        This scaffold expects `weavert` to be installed in the same environment that runs the entrypoint.

        1. `python3 -m venv .venv`
        2. `source .venv/bin/activate`
        3. `python -m pip install -e /path/to/weave-ai-runtime/packages/core`
        4. `python -m pip install -e .`
        5. `export OPENAI_API_KEY=your-key`
        6. `python live_smoke.py`

        If you are using a published `weavert` package instead of a source checkout, install that package in step 3.

        If preflight fails, fix the reported environment or route issue first. The scaffold does not silently drop back to an offline path.
        '''
    ).lstrip()



def _python(source: str) -> str:
    return dedent(source).lstrip()



def _normalize_project_slug(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return normalized or "weavert-starter"



def _resolve_project_name(destination: Path, project_name: str | None) -> str:
    if project_name is not None and project_name.strip():
        return project_name.strip()
    if destination.name:
        return destination.name
    return "weavert-starter"



__all__ = [
    "StarterScaffoldDefinition",
    "StarterScaffoldGenerationResult",
    "StarterScaffoldName",
    "generate_starter_scaffold",
    "main",
    "official_starter_scaffold",
    "official_starter_scaffold_catalog",
]


if __name__ == "__main__":
    raise SystemExit(main())
