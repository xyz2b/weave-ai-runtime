from pathlib import Path

from runtime.definitions import DefinitionSource
from runtime.registries import DefinitionDiscovery
from runtime.runtime_kernel import DefinitionSourcePaths


def test_definition_discovery_loads_tools_agents_and_skills(tmp_path: Path) -> None:
    tools_dir = tmp_path / "tools"
    agents_dir = tmp_path / "agents"
    skills_dir = tmp_path / "skills" / "review"
    tools_dir.mkdir(parents=True)
    agents_dir.mkdir(parents=True)
    skills_dir.mkdir(parents=True)

    (tools_dir / "grep.yaml").write_text(
        """
name: grep
description: Search text
aliases:
  - Grep
traits:
  readOnly: true
  concurrencySafe: true
""".strip(),
        encoding="utf-8",
    )
    (tools_dir / "hello.py").write_text(
        """
from runtime.definitions import ToolDefinition

TOOL_DEFINITION = ToolDefinition(name="hello", description="Say hello")
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
  - grep
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
  - grep
paths:
  - src/**/*.py
user-invocable: false
---
# Review

Check the diff carefully.
""".strip(),
        encoding="utf-8",
    )

    report = DefinitionDiscovery(
        (DefinitionSourcePaths(DefinitionSource.USER, tmp_path),)
    ).discover()

    assert {tool.name for tool in report.tools} == {"grep", "hello"}
    assert report.agents[0].name == "reviewer"
    assert report.agents[0].background is True
    assert report.skills[0].name == "review"
    assert report.skills[0].allowed_tools == ("read", "grep")
    assert report.skills[0].user_invocable is False
    assert any(diag.code == "definition_validation_error" for diag in report.diagnostics)

