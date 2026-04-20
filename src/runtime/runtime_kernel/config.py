from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping

from ..agent_execution import ChildRunStore
from ..definitions import (
    AgentDefinition,
    DefinitionSource,
    InvocationProvider,
    SkillDefinition,
    ToolDefinition,
)
from ..hosts.base import HostFactory
from ..teammate_orchestration.models import TeammateOrchestrationConfig
from ..turn_engine.models import ModelClient, NormalizedModelCapabilities, TranscriptStore

if TYPE_CHECKING:
    from ..tool_runtime import AskUserHandler, PermissionHandler, ToolRefreshCallback


@dataclass(frozen=True, slots=True)
class DefinitionSourcePaths:
    source: DefinitionSource
    root: Path
    tools_subdir: str = "tools"
    agents_subdir: str = "agents"
    skills_subdir: str = "skills"
    enabled: bool = True

    @property
    def tools_dir(self) -> Path:
        return self.root / self.tools_subdir

    @property
    def agents_dir(self) -> Path:
        return self.root / self.agents_subdir

    @property
    def skills_dir(self) -> Path:
        return self.root / self.skills_subdir


@dataclass(slots=True)
class BuiltinPackConfig:
    tools_enabled: bool = True
    agents_enabled: bool = True
    skills_enabled: bool = True
    disabled_tools: set[str] = field(default_factory=set)
    disabled_agents: set[str] = field(default_factory=set)
    disabled_skills: set[str] = field(default_factory=set)
    tool_replacements: dict[str, ToolDefinition] = field(default_factory=dict)
    agent_replacements: dict[str, AgentDefinition] = field(default_factory=dict)
    skill_replacements: dict[str, SkillDefinition] = field(default_factory=dict)
    extra_tools: list[ToolDefinition] = field(default_factory=list)
    extra_agents: list[AgentDefinition] = field(default_factory=list)
    extra_skills: list[SkillDefinition] = field(default_factory=list)

    def tool_enabled(self, name: str) -> bool:
        return self.tools_enabled and name not in self.disabled_tools

    def agent_enabled(self, name: str) -> bool:
        return self.agents_enabled and name not in self.disabled_agents

    def skill_enabled(self, name: str) -> bool:
        return self.skills_enabled and name not in self.disabled_skills


@dataclass(frozen=True, slots=True)
class HostBinding:
    name: str
    factory: HostFactory
    config: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ModelRouteBinding:
    client: ModelClient
    default_model: str | None = None
    provider_name: str | None = None
    capabilities: NormalizedModelCapabilities | None = None


@dataclass(slots=True)
class RuntimeConfig:
    runtime_id: str = "default"
    working_directory: Path = field(default_factory=Path.cwd)
    discovery_sources: tuple[DefinitionSourcePaths, ...] = ()
    builtins: BuiltinPackConfig = field(default_factory=BuiltinPackConfig)
    host_bindings: tuple[HostBinding, ...] = ()
    model_client: ModelClient | None = None
    model_routes: dict[str, ModelRouteBinding] = field(default_factory=dict)
    default_model_route: str | None = None
    transcript_store: TranscriptStore | None = None
    child_run_store: ChildRunStore | None = None
    default_agent: str = "main-router"
    system_prompt: str = ""
    permission_handler: PermissionHandler | None = None
    ask_user_handler: AskUserHandler | None = None
    tool_refresh_callback: ToolRefreshCallback | None = None
    extra_invocation_providers: list[InvocationProvider] = field(default_factory=list)
    memory_config: Mapping[str, Any] | None = None
    teammate_orchestration: TeammateOrchestrationConfig | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def for_project(cls, project_root: Path) -> "RuntimeConfig":
        user_root = Path.home() / ".runtime"
        project_runtime_dir = project_root / ".runtime"
        return cls(
            working_directory=project_root,
            discovery_sources=(
                DefinitionSourcePaths(DefinitionSource.USER, user_root),
                DefinitionSourcePaths(DefinitionSource.PROJECT, project_runtime_dir),
            ),
        )
