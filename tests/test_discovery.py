from pathlib import Path

from weavert.definitions import DefinitionSource
from weavert.registries import DefinitionDiscovery
from weavert.runtime_kernel import DefinitionSourcePaths


def test_definition_discovery_loads_python_tools_agents_and_skills(tmp_path: Path) -> None:
    tools_dir = tmp_path / "tools"
    agents_dir = tmp_path / "agents"
    skills_dir = tmp_path / "skills" / "review"
    tools_dir.mkdir(parents=True)
    agents_dir.mkdir(parents=True)
    skills_dir.mkdir(parents=True)

    (tools_dir / "hello.py").write_text(
        """
from weavert.definitions import ToolDefinition

def execute(tool_input, context):
    return {"tool": "hello"}

TOOL_DEFINITION = ToolDefinition(name="hello", description="Say hello", execute=execute)
""".strip(),
        encoding="utf-8",
    )
    (tools_dir / "echo.py").write_text(
        """
from weavert.definitions import ToolDefinition

def execute(tool_input, context):
    return {"tool": "echo"}

TOOL = ToolDefinition(name="echo", description="Echo text", execute=execute)
""".strip(),
        encoding="utf-8",
    )
    (tools_dir / "builder.py").write_text(
        """
from weavert.definitions import ToolDefinition

def execute(tool_input, context):
    return {"tool": "builder"}

def build_tool_definition():
    return ToolDefinition(name="builder", description="Build a tool", execute=execute)
""".strip(),
        encoding="utf-8",
    )
    (agents_dir / "reviewer.md").write_text(
        """
---
name: reviewer
description: Review code changes
tools:
  - read
  - hello
permissionMode: dontAsk
maxTurns: 5
background: true
memory: project
isolation: worktree
---
You are a reviewer.
""".strip(),
        encoding="utf-8",
    )
    (agents_dir / "broken.md").write_text(
        """
---
name: broken
---
""".strip(),
        encoding="utf-8",
    )
    (skills_dir / "SKILL.md").write_text(
        """
---
description: Review code before shipping
context: fork
agent: reviewer
allowed-tools:
  - read
  - hello
paths:
  - src/**/*.py
user-invocable: false
---
# Review

Check the diff carefully.
""".strip(),
        encoding="utf-8",
    )

    report = DefinitionDiscovery((DefinitionSourcePaths(DefinitionSource.USER, tmp_path),)).discover()

    assert {tool.name for tool in report.tools} == {"hello", "echo", "builder"}
    assert report.agents[0].name == "reviewer"
    assert report.agents[0].background is True
    assert report.skills[0].name == "review"
    assert report.skills[0].allowed_tools == ("read", "hello")
    assert report.skills[0].user_invocable is False
    assert any(diag.code == "definition_validation_error" for diag in report.diagnostics)


def test_definition_discovery_rejects_legacy_file_backed_tools_with_migration_diagnostics(
    tmp_path: Path,
) -> None:
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir(parents=True)

    legacy_yaml = tools_dir / "grep.yaml"
    legacy_yaml.write_text(
        """
name: grep
description: Search text
""".strip(),
        encoding="utf-8",
    )
    legacy_json = tools_dir / "inspect.json"
    legacy_json.write_text(
        """
{"name": "inspect", "description": "Inspect data"}
""".strip(),
        encoding="utf-8",
    )
    (tools_dir / "hello.py").write_text(
        """
from weavert.definitions import ToolDefinition

def execute(tool_input, context):
    return {"tool": "hello"}

TOOL_DEFINITION = ToolDefinition(name="hello", description="Say hello", execute=execute)
""".strip(),
        encoding="utf-8",
    )

    report = DefinitionDiscovery((DefinitionSourcePaths(DefinitionSource.USER, tmp_path),)).discover()

    assert {tool.name for tool in report.tools} == {"hello"}
    diagnostics = {diag.location: diag for diag in report.diagnostics}
    assert diagnostics[str(legacy_yaml)].details["rejection_reason"] == "legacy_file_backed_tool_format"
    assert diagnostics[str(legacy_json)].details["rejection_reason"] == "legacy_file_backed_tool_format"
    assert str(tools_dir) in diagnostics[str(legacy_yaml)].details["migration_target"]
    assert ".py module" in diagnostics[str(legacy_yaml)].details["migration_target"]
    assert "no longer supported" in diagnostics[str(legacy_json)].message


def test_definition_discovery_uses_configured_tools_dir_in_migration_diagnostics(tmp_path: Path) -> None:
    tools_dir = tmp_path / "custom-tools"
    tools_dir.mkdir(parents=True)
    legacy_yaml = tools_dir / "grep.yaml"
    legacy_yaml.write_text(
        """
name: grep
description: Search text
""".strip(),
        encoding="utf-8",
    )

    report = DefinitionDiscovery(
        (DefinitionSourcePaths(DefinitionSource.USER, tmp_path, tools_subdir="custom-tools"),)
    ).discover()

    assert report.tools == ()
    assert len(report.diagnostics) == 1
    diagnostic = report.diagnostics[0]
    assert diagnostic.details["rejection_reason"] == "legacy_file_backed_tool_format"
    assert str(tools_dir) in diagnostic.details["migration_target"]
    assert ".weavert/tools/" not in diagnostic.details["migration_target"]


def test_definition_discovery_rejects_mapping_style_python_exports(tmp_path: Path) -> None:
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir(parents=True)
    mapping_tool = tools_dir / "mapping.py"
    mapping_tool.write_text(
        """
TOOL_DEFINITION = {
    "name": "mapping-tool",
    "description": "Legacy mapping export",
}
""".strip(),
        encoding="utf-8",
    )

    report = DefinitionDiscovery((DefinitionSourcePaths(DefinitionSource.USER, tmp_path),)).discover()

    assert report.tools == ()
    assert len(report.diagnostics) == 1
    diagnostic = report.diagnostics[0]
    assert diagnostic.location == str(mapping_tool)
    assert diagnostic.details["rejection_reason"] == "mapping_style_python_export"
    assert diagnostic.details["exported_type"] == "dict"
    assert "concrete ToolDefinition" in diagnostic.message


def test_definition_discovery_rejects_python_tools_without_supported_exports(tmp_path: Path) -> None:
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir(parents=True)
    missing_exports = tools_dir / "missing_exports.py"
    missing_exports.write_text(
        """
# module intentionally exports nothing
""".strip(),
        encoding="utf-8",
    )

    report = DefinitionDiscovery((DefinitionSourcePaths(DefinitionSource.USER, tmp_path),)).discover()

    assert report.tools == ()
    assert len(report.diagnostics) == 1
    diagnostic = report.diagnostics[0]
    assert diagnostic.location == str(missing_exports)
    assert diagnostic.code == "definition_validation_error"
    assert diagnostic.details["rejection_reason"] == "missing_python_tool_export"
    assert str(tools_dir) in diagnostic.details["migration_target"]
    assert "must export TOOL_DEFINITION" in diagnostic.message


def test_definition_discovery_rejects_non_callable_build_tool_definition_exports(tmp_path: Path) -> None:
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir(parents=True)
    invalid_builder = tools_dir / "invalid_builder.py"
    invalid_builder.write_text(
        """
build_tool_definition = 123
""".strip(),
        encoding="utf-8",
    )

    report = DefinitionDiscovery((DefinitionSourcePaths(DefinitionSource.USER, tmp_path),)).discover()

    assert report.tools == ()
    assert len(report.diagnostics) == 1
    diagnostic = report.diagnostics[0]
    assert diagnostic.location == str(invalid_builder)
    assert diagnostic.code == "definition_validation_error"
    assert diagnostic.details["rejection_reason"] == "invalid_python_tool_export"
    assert diagnostic.details["exported_type"] == "int"
    assert diagnostic.details["export_name"] == "build_tool_definition"
    assert str(tools_dir) in diagnostic.details["migration_target"]
    assert "callable returning a ToolDefinition" in diagnostic.message


def test_definition_discovery_rejects_failing_build_tool_definition_exports(tmp_path: Path) -> None:
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir(parents=True)
    failing_builder = tools_dir / "failing_builder.py"
    failing_builder.write_text(
        """
def build_tool_definition():
    raise RuntimeError("boom")
""".strip(),
        encoding="utf-8",
    )

    report = DefinitionDiscovery((DefinitionSourcePaths(DefinitionSource.USER, tmp_path),)).discover()

    assert report.tools == ()
    assert len(report.diagnostics) == 1
    diagnostic = report.diagnostics[0]
    assert diagnostic.location == str(failing_builder)
    assert diagnostic.code == "definition_validation_error"
    assert diagnostic.details["rejection_reason"] == "invalid_python_tool_export"
    assert diagnostic.details["exported_type"] == "build_tool_definition"
    assert diagnostic.details["export_error"] == "boom"
    assert str(tools_dir) in diagnostic.details["migration_target"]
    assert "build_tool_definition() failed" in diagnostic.message


def test_definition_discovery_rejects_file_backed_tools_without_execute(tmp_path: Path) -> None:
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir(parents=True)
    missing_execute = tools_dir / "missing_execute.py"
    missing_execute.write_text(
        """
from weavert.definitions import ToolDefinition

TOOL_DEFINITION = ToolDefinition(
    name="missing-execute",
    description="No execute handler",
)
""".strip(),
        encoding="utf-8",
    )

    report = DefinitionDiscovery((DefinitionSourcePaths(DefinitionSource.USER, tmp_path),)).discover()

    assert report.tools == ()
    assert len(report.diagnostics) == 1
    diagnostic = report.diagnostics[0]
    assert diagnostic.location == str(missing_execute)
    assert diagnostic.details["rejection_reason"] == "missing_execute"
    assert diagnostic.details["tool_name"] == "missing-execute"
    assert "must provide execute" in diagnostic.message
