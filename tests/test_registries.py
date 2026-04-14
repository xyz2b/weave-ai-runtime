from pathlib import Path

from claude_agent_runtime.definitions import (
    AgentDefinition,
    DefinitionOrigin,
    DefinitionSource,
    SkillDefinition,
    ToolDefinition,
)
from claude_agent_runtime.registries import AgentRegistry, SkillRegistry, ToolRegistry


def origin(source: DefinitionSource, name: str) -> DefinitionOrigin:
    return DefinitionOrigin(source, path=Path(f"/tmp/{name}"))


def test_tool_registry_resolves_aliases_and_priority() -> None:
    registry = ToolRegistry()
    user_tool = ToolDefinition(
        name="read",
        description="user read",
        aliases=("Reader",),
        origin=origin(DefinitionSource.USER, "user-tool.yaml"),
    )
    bundled_tool = ToolDefinition(
        name="read",
        description="bundled read",
        aliases=("Read",),
        origin=origin(DefinitionSource.BUNDLED, "builtin-tool.yaml"),
    )

    assert registry.register(user_tool).action == "registered"
    outcome = registry.register(bundled_tool)

    assert outcome.action == "replaced"
    assert registry.get("read") is not None
    assert registry.get("read").description == "bundled read"
    assert registry.get("Read") is not None
    assert registry.get("Read").description == "bundled read"
    assert any(diag.code == "definition_shadowed" for diag in outcome.diagnostics)


def test_tool_registry_drops_conflicting_aliases() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="read",
            description="read",
            aliases=("View",),
            origin=origin(DefinitionSource.BUNDLED, "read.yaml"),
        )
    )

    outcome = registry.register(
        ToolDefinition(
            name="inspect",
            description="inspect",
            aliases=("View", "Inspect"),
            origin=origin(DefinitionSource.USER, "inspect.yaml"),
        )
    )

    inspect_tool = registry.get("inspect")
    assert inspect_tool is not None
    assert inspect_tool.aliases == ("Inspect",)
    assert any(diag.code == "tool_alias_dropped" for diag in outcome.diagnostics)


def test_agent_registry_prefers_bundled_over_user() -> None:
    registry = AgentRegistry()
    bundled = AgentDefinition(
        name="main-router",
        description="built in",
        prompt="builtin prompt",
        origin=origin(DefinitionSource.BUNDLED, "main-router.md"),
    )
    project = AgentDefinition(
        name="main-router",
        description="project override",
        prompt="project prompt",
        origin=origin(DefinitionSource.PROJECT, "main-router-project.md"),
    )

    registry.register(bundled)
    outcome = registry.register(project)

    assert outcome.action == "skipped"
    assert registry.get("main-router") is not None
    assert registry.get("main-router").description == "built in"


def test_skill_registry_activation_and_path_scoping() -> None:
    registry = SkillRegistry()
    registry.register(
        SkillDefinition(
            name="always-on",
            description="always",
            content="always",
            origin=origin(DefinitionSource.BUNDLED, "always/SKILL.md"),
        )
    )
    registry.register(
        SkillDefinition(
            name="python-only",
            description="python",
            content="python",
            paths=("src/**/*.py",),
            origin=origin(DefinitionSource.USER, "python-only/SKILL.md"),
        )
    )

    assert {skill.name for skill in registry.resolve_active(paths=["src/app/main.py"])} == {
        "always-on",
        "python-only",
    }
    assert {skill.name for skill in registry.resolve_active(paths=["README.md"])} == {
        "always-on",
    }

    registry.set_active("always-on", False)
    assert registry.is_active("always-on") is False
    assert {skill.name for skill in registry.resolve_active(paths=["src/app/main.py"])} == {
        "python-only",
    }

