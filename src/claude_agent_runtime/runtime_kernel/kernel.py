from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..builtins import load_builtin_pack
from ..definitions import AgentDefinition, SkillDefinition, ToolDefinition
from ..diagnostics import Diagnostic, DiagnosticSeverity
from ..errors import RegistryConflictError
from ..hosts.base import BoundHostRuntime, HostAdapter, NullHostAdapter
from ..registries import AgentRegistry, DefinitionDiscovery, SkillRegistry, ToolRegistry
from .config import RuntimeConfig


@dataclass(slots=True)
class RuntimeKernel:
    config: RuntimeConfig
    tool_registry: ToolRegistry
    agent_registry: AgentRegistry
    skill_registry: SkillRegistry
    diagnostics: tuple[Diagnostic, ...] = ()
    model_client: Any = None
    transcript_store: Any = None
    hosts: dict[str, HostAdapter] = field(default_factory=dict)


def build_runtime_kernel(config: RuntimeConfig) -> RuntimeKernel:
    tool_registry = ToolRegistry()
    agent_registry = AgentRegistry()
    skill_registry = SkillRegistry()
    diagnostics: list[Diagnostic] = []

    builtin_pack = load_builtin_pack()
    _register_builtin_tools(tool_registry, config, builtin_pack.tools, diagnostics)
    _register_builtin_agents(agent_registry, config, builtin_pack.agents, diagnostics)
    _register_builtin_skills(skill_registry, config, builtin_pack.skills, diagnostics)

    discovery = DefinitionDiscovery(config.discovery_sources)
    discovered = discovery.discover()
    diagnostics.extend(discovered.diagnostics)
    _register_all(tool_registry, discovered.tools, diagnostics)
    _register_all(agent_registry, discovered.agents, diagnostics)
    _register_all(skill_registry, discovered.skills, diagnostics)

    kernel = RuntimeKernel(
        config=config,
        tool_registry=tool_registry,
        agent_registry=agent_registry,
        skill_registry=skill_registry,
        diagnostics=tuple(diagnostics),
        model_client=config.model_client,
        transcript_store=config.transcript_store,
    )
    for binding in config.host_bindings:
        kernel.hosts[binding.name] = binding.factory(binding.name, binding.config, kernel)
    return kernel


def assemble_host_runtime(
    config: RuntimeConfig,
    host_name: str | None = None,
) -> BoundHostRuntime:
    kernel = build_runtime_kernel(config)
    if host_name is None:
        host = next(iter(kernel.hosts.values()), NullHostAdapter())
    else:
        host = kernel.hosts.get(host_name)
        if host is None:
            raise KeyError(host_name)
    return BoundHostRuntime(kernel=kernel, host=host)


def _register_builtin_tools(
    registry: ToolRegistry,
    config: RuntimeConfig,
    definitions: tuple[ToolDefinition, ...],
    diagnostics: list[Diagnostic],
) -> None:
    for definition in definitions:
        if not config.builtins.tool_enabled(definition.name):
            continue
        replacement = config.builtins.tool_replacements.get(definition.name, definition)
        diagnostics.extend(registry.register(replacement).diagnostics)
    for extra in config.builtins.extra_tools:
        diagnostics.extend(registry.register(extra).diagnostics)


def _register_builtin_agents(
    registry: AgentRegistry,
    config: RuntimeConfig,
    definitions: tuple[AgentDefinition, ...],
    diagnostics: list[Diagnostic],
) -> None:
    for definition in definitions:
        if not config.builtins.agent_enabled(definition.name):
            continue
        replacement = config.builtins.agent_replacements.get(definition.name, definition)
        diagnostics.extend(registry.register(replacement).diagnostics)
    for extra in config.builtins.extra_agents:
        diagnostics.extend(registry.register(extra).diagnostics)


def _register_builtin_skills(
    registry: SkillRegistry,
    config: RuntimeConfig,
    definitions: tuple[SkillDefinition, ...],
    diagnostics: list[Diagnostic],
) -> None:
    for definition in definitions:
        if not config.builtins.skill_enabled(definition.name):
            continue
        replacement = config.builtins.skill_replacements.get(definition.name, definition)
        diagnostics.extend(registry.register(replacement).diagnostics)
    for extra in config.builtins.extra_skills:
        diagnostics.extend(registry.register(extra).diagnostics)


def _register_all(
    registry: ToolRegistry | AgentRegistry | SkillRegistry,
    definitions: tuple[ToolDefinition, ...]
    | tuple[AgentDefinition, ...]
    | tuple[SkillDefinition, ...],
    diagnostics: list[Diagnostic],
) -> None:
    for definition in definitions:
        try:
            diagnostics.extend(registry.register(definition).diagnostics)
        except RegistryConflictError as exc:
            diagnostics.append(
                Diagnostic(
                    severity=DiagnosticSeverity.ERROR,
                    code=exc.code.value,
                    message=str(exc),
                    definition_type=getattr(registry, "definition_type", "definition"),
                    source=definition.origin.source.value,
                    location=definition.origin.label,
                    details=exc.details,
                )
            )
