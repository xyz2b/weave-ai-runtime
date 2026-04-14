from pathlib import Path

from claude_agent_runtime.definitions import (
    AgentDefinition,
    DefinitionOrigin,
    DefinitionSource,
)
from claude_agent_runtime.hosts.base import NullHostAdapter
from claude_agent_runtime.runtime_kernel import (
    BuiltinPackConfig,
    DefinitionSourcePaths,
    HostBinding,
    RuntimeConfig,
    assemble_host_runtime,
    build_runtime_kernel,
)


def test_runtime_kernel_applies_builtin_switches_and_discovers_project_defs(
    tmp_path: Path,
) -> None:
    agents_dir = tmp_path / "agents"
    skills_dir = tmp_path / "skills" / "project-skill"
    agents_dir.mkdir(parents=True)
    skills_dir.mkdir(parents=True)

    (agents_dir / "main-router.md").write_text(
        """
---
name: main-router
description: project override
---
project router
""".strip(),
        encoding="utf-8",
    )
    (skills_dir / "SKILL.md").write_text(
        """
---
description: project skill
---
project skill body
""".strip(),
        encoding="utf-8",
    )

    replacement = AgentDefinition(
        name="main-router",
        description="custom builtin router",
        prompt="custom router prompt",
        origin=DefinitionOrigin(DefinitionSource.BUNDLED, path=Path("<host>")),
    )

    config = RuntimeConfig(
        working_directory=tmp_path,
        discovery_sources=(DefinitionSourcePaths(DefinitionSource.PROJECT, tmp_path),),
        builtins=BuiltinPackConfig(
            disabled_tools={"read"},
            agent_replacements={"main-router": replacement},
            disabled_skills={"debug"},
        ),
    )

    kernel = build_runtime_kernel(config)

    assert kernel.tool_registry.get("read") is None
    assert kernel.agent_registry.get("main-router") is not None
    assert kernel.agent_registry.get("main-router").description == "custom builtin router"
    assert kernel.agent_registry.get("main-router").prompt == "custom router prompt"
    assert kernel.skill_registry.get("project-skill") is not None
    assert kernel.skill_registry.get("debug") is None
    assert any(diag.code == "definition_skipped" for diag in kernel.diagnostics)


def test_host_assembly_entrypoint_binds_host(tmp_path: Path) -> None:
    def factory(name: str, config: dict[str, str], kernel: object) -> NullHostAdapter:
        _ = config, kernel
        return NullHostAdapter(name=name)

    config = RuntimeConfig(
        working_directory=tmp_path,
        host_bindings=(HostBinding(name="cli", factory=factory, config={"mode": "interactive"}),),
    )

    runtime = assemble_host_runtime(config, host_name="cli")

    assert runtime.host.name == "cli"
    assert runtime.kernel.agent_registry.get("main-router") is not None
