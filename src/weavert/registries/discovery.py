from __future__ import annotations

from collections.abc import Mapping
import importlib.util
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from .._frontmatter import (
    coerce_bool,
    coerce_mapping,
    coerce_string_list,
    extract_markdown_description,
    parse_frontmatter_document,
)
from ..definitions import (
    AgentDefinition,
    DefinitionOrigin,
    IsolationMode,
    MemoryScope,
    PermissionMode,
    SkillDefinition,
    SkillExecutionContext,
    SkillShell,
    ToolDefinition,
)
from ..diagnostics import Diagnostic, DiagnosticSeverity
from ..errors import DefinitionLoadError, DefinitionValidationError
from ..runtime_kernel.config import DefinitionSourcePaths


@dataclass(frozen=True, slots=True)
class DiscoveryReport:
    tools: tuple[ToolDefinition, ...] = ()
    agents: tuple[AgentDefinition, ...] = ()
    skills: tuple[SkillDefinition, ...] = ()
    diagnostics: tuple[Diagnostic, ...] = ()


class DefinitionDiscovery:
    _LEGACY_TOOL_FILE_SUFFIXES = frozenset({".json", ".yaml", ".yml"})
    _FILE_BACKED_TOOL_MIGRATION_TARGET = (
        "Replace this file with a .py module under .weavert/tools/ that exports "
        "TOOL_DEFINITION, TOOL, or build_tool_definition() returning a ToolDefinition with execute."
    )

    def __init__(self, sources: tuple[DefinitionSourcePaths, ...]) -> None:
        self._sources = tuple(source for source in sources if source.enabled)

    def discover(self) -> DiscoveryReport:
        tools: list[ToolDefinition] = []
        agents: list[AgentDefinition] = []
        skills: list[SkillDefinition] = []
        diagnostics: list[Diagnostic] = []

        for source in self._sources:
            loaded_tools, tool_diags = self._discover_tools(source)
            loaded_agents, agent_diags = self._discover_agents(source)
            loaded_skills, skill_diags = self._discover_skills(source)
            tools.extend(loaded_tools)
            agents.extend(loaded_agents)
            skills.extend(loaded_skills)
            diagnostics.extend(tool_diags)
            diagnostics.extend(agent_diags)
            diagnostics.extend(skill_diags)

        return DiscoveryReport(
            tools=tuple(tools),
            agents=tuple(agents),
            skills=tuple(skills),
            diagnostics=tuple(diagnostics),
        )

    def _discover_tools(
        self,
        source: DefinitionSourcePaths,
    ) -> tuple[list[ToolDefinition], list[Diagnostic]]:
        tools: list[ToolDefinition] = []
        diagnostics: list[Diagnostic] = []
        for path in sorted(source.tools_dir.glob("*")):
            if not path.is_file():
                continue
            origin = DefinitionOrigin(source.source, path=path, root=source.root)
            suffix = path.suffix.lower()
            if suffix in self._LEGACY_TOOL_FILE_SUFFIXES:
                diagnostics.append(self._unsupported_legacy_tool_diagnostic(origin))
                continue
            if suffix != ".py":
                continue
            try:
                tools.append(self._load_tool_definition(path, origin))
            except Exception as exc:  # pragma: no cover - defensive boundary
                diagnostics.append(self._diagnostic_from_exception(exc, "tool", origin))
        return tools, diagnostics

    def _discover_agents(
        self,
        source: DefinitionSourcePaths,
    ) -> tuple[list[AgentDefinition], list[Diagnostic]]:
        agents: list[AgentDefinition] = []
        diagnostics: list[Diagnostic] = []
        for path in sorted(source.agents_dir.glob("*.md")):
            origin = DefinitionOrigin(source.source, path=path, root=source.root)
            try:
                agents.append(self._load_agent_definition(path, origin))
            except Exception as exc:  # pragma: no cover - defensive boundary
                diagnostics.append(self._diagnostic_from_exception(exc, "agent", origin))
        return agents, diagnostics

    def _discover_skills(
        self,
        source: DefinitionSourcePaths,
    ) -> tuple[list[SkillDefinition], list[Diagnostic]]:
        skills: list[SkillDefinition] = []
        diagnostics: list[Diagnostic] = []
        for path in sorted(source.skills_dir.glob("**/SKILL.md")):
            origin = DefinitionOrigin(source.source, path=path, root=source.root)
            try:
                skills.append(self._load_skill_definition(path, origin))
            except Exception as exc:  # pragma: no cover - defensive boundary
                diagnostics.append(self._diagnostic_from_exception(exc, "skill", origin))
        return skills, diagnostics

    def _load_tool_definition(self, path: Path, origin: DefinitionOrigin) -> ToolDefinition:
        if path.suffix.lower() != ".py":
            raise DefinitionLoadError(f"Unsupported tool definition format: {path.suffix}", path=str(path))
        return self._tool_from_python(path, origin)

    def _tool_from_python(self, path: Path, origin: DefinitionOrigin) -> ToolDefinition:
        module_name = f"_runtime_tool_{abs(hash(path.resolve()))}"
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise DefinitionLoadError("Unable to import tool definition module", path=str(path))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        exported = getattr(module, "TOOL_DEFINITION", None)
        if exported is None:
            exported = getattr(module, "TOOL", None)
        if exported is None and hasattr(module, "build_tool_definition"):
            exported = module.build_tool_definition()
        if exported is None:
            raise DefinitionLoadError(
                "Python tool definition module must export TOOL_DEFINITION, TOOL, "
                "or build_tool_definition()",
                path=str(path),
            )
        if isinstance(exported, Mapping):
            raise DefinitionValidationError(
                "Python file-backed tools must export a concrete ToolDefinition; mapping-style payloads are not supported.",
                path=str(path),
                rejection_reason="mapping_style_python_export",
                exported_type=type(exported).__name__,
                migration_target=self._FILE_BACKED_TOOL_MIGRATION_TARGET,
            )
        if not isinstance(exported, ToolDefinition):
            raise DefinitionValidationError(
                "Python tool definition module must resolve to a ToolDefinition instance.",
                path=str(path),
                rejection_reason="invalid_python_tool_export",
                exported_type=type(exported).__name__,
                migration_target=self._FILE_BACKED_TOOL_MIGRATION_TARGET,
            )
        definition = replace(exported, origin=origin)
        if definition.execute is None:
            raise DefinitionValidationError(
                "Python file-backed tools must provide execute in their ToolDefinition.",
                path=str(path),
                rejection_reason="missing_execute",
                tool_name=definition.name,
                migration_target=self._FILE_BACKED_TOOL_MIGRATION_TARGET,
            )
        return definition

    def _unsupported_legacy_tool_diagnostic(self, origin: DefinitionOrigin) -> Diagnostic:
        failure = DefinitionValidationError(
            "Legacy .json/.yaml/.yml file-backed tools are no longer supported; migrate this tool to a Python module.",
            path=str(origin.path),
            rejection_reason="legacy_file_backed_tool_format",
            migration_target=self._FILE_BACKED_TOOL_MIGRATION_TARGET,
        )
        return self._diagnostic_from_exception(failure, "tool", origin)

    def _load_agent_definition(self, path: Path, origin: DefinitionOrigin) -> AgentDefinition:
        frontmatter, body = parse_frontmatter_document(path.read_text(encoding="utf-8"))
        name = str(frontmatter.get("name") or path.stem).strip()
        description = str(frontmatter.get("description") or "").strip()
        prompt = body.strip()
        if not name or not description or not prompt:
            raise DefinitionValidationError(
                "Agent definitions require name, description, and prompt body",
                path=str(path),
            )

        return AgentDefinition(
            name=name,
            description=description,
            prompt=prompt,
            tools=coerce_string_list(frontmatter.get("tools")),
            disallowed_tools=coerce_string_list(frontmatter.get("disallowedTools")),
            skills=coerce_string_list(frontmatter.get("skills")),
            model=self._optional_string(frontmatter.get("model")),
            model_route=self._optional_string(frontmatter.get("modelRoute")),
            effort=self._coerce_effort(frontmatter.get("effort")),
            permission_mode=self._coerce_permission_mode(frontmatter.get("permissionMode")),
            max_turns=self._coerce_positive_int(frontmatter.get("maxTurns")),
            background=coerce_bool(frontmatter.get("background"), default=False),
            memory=self._coerce_memory_scope(frontmatter.get("memory")),
            isolation=self._coerce_isolation(frontmatter.get("isolation")),
            hooks=coerce_mapping(frontmatter.get("hooks"), field_name="hooks"),
            initial_prompt=self._optional_string(frontmatter.get("initialPrompt")),
            critical_system_reminder=self._optional_string(
                frontmatter.get("criticalSystemReminder_EXPERIMENTAL")
            ),
            mcp_servers=tuple(frontmatter.get("mcpServers", []) or ()),
            metadata={"raw_frontmatter": frontmatter},
            origin=origin,
        )

    def _load_skill_definition(self, path: Path, origin: DefinitionOrigin) -> SkillDefinition:
        frontmatter, body = parse_frontmatter_document(path.read_text(encoding="utf-8"))
        slug = path.parent.name
        description = str(frontmatter.get("description") or "").strip() or extract_markdown_description(body)

        return SkillDefinition(
            name=slug,
            display_name=self._optional_string(frontmatter.get("name")),
            description=description,
            content=body.strip(),
            when_to_use=self._optional_string(frontmatter.get("when_to_use")),
            version=self._optional_string(frontmatter.get("version")),
            user_invocable=coerce_bool(frontmatter.get("user-invocable"), default=True),
            disable_model_invocation=coerce_bool(
                frontmatter.get("disable-model-invocation"),
                default=False,
            ),
            argument_hint=self._optional_string(frontmatter.get("argument-hint")),
            argument_names=coerce_string_list(frontmatter.get("arguments")),
            execution_context=self._coerce_skill_context(frontmatter.get("context")),
            agent=self._optional_string(frontmatter.get("agent")),
            model=self._optional_string(frontmatter.get("model")),
            effort=self._coerce_effort(frontmatter.get("effort")),
            allowed_tools=coerce_string_list(frontmatter.get("allowed-tools")),
            shell=self._coerce_skill_shell(frontmatter.get("shell")),
            hooks=coerce_mapping(frontmatter.get("hooks"), field_name="hooks"),
            paths=coerce_string_list(frontmatter.get("paths")),
            metadata={"raw_frontmatter": frontmatter},
            origin=origin,
        )

    @staticmethod
    def _optional_string(value: Any) -> str | None:
        if value is None:
            return None
        stringified = str(value).strip()
        return stringified or None

    @staticmethod
    def _coerce_positive_int(value: Any) -> int | None:
        if value is None:
            return None
        if isinstance(value, int) and value > 0:
            return value
        raise DefinitionValidationError("Expected a positive integer")

    @staticmethod
    def _coerce_effort(value: Any) -> str | int | None:
        if value is None:
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            lowered = value.strip()
            if lowered:
                return lowered
        raise DefinitionValidationError("Expected effort to be a string or integer")

    @staticmethod
    def _coerce_permission_mode(value: Any) -> PermissionMode | None:
        if value is None:
            return None
        try:
            return PermissionMode(str(value))
        except ValueError as exc:
            raise DefinitionValidationError(f"Invalid permission mode: {value}") from exc

    @staticmethod
    def _coerce_memory_scope(value: Any) -> MemoryScope | None:
        if value is None:
            return None
        try:
            return MemoryScope(str(value))
        except ValueError as exc:
            raise DefinitionValidationError(f"Invalid memory scope: {value}") from exc

    @staticmethod
    def _coerce_isolation(value: Any) -> IsolationMode | None:
        if value is None:
            return None
        try:
            return IsolationMode(str(value))
        except ValueError as exc:
            raise DefinitionValidationError(f"Invalid isolation mode: {value}") from exc

    @staticmethod
    def _coerce_skill_context(value: Any) -> SkillExecutionContext:
        if value is None:
            return SkillExecutionContext.INLINE
        try:
            return SkillExecutionContext(str(value))
        except ValueError as exc:
            raise DefinitionValidationError(f"Invalid skill execution context: {value}") from exc

    @staticmethod
    def _coerce_skill_shell(value: Any) -> SkillShell | None:
        if value is None:
            return None
        try:
            return SkillShell(str(value))
        except ValueError as exc:
            raise DefinitionValidationError(f"Invalid skill shell: {value}") from exc

    @staticmethod
    def _diagnostic_from_exception(
        exc: Exception,
        definition_type: str,
        origin: DefinitionOrigin,
    ) -> Diagnostic:
        code = "definition_discovery_error"
        if isinstance(exc, DefinitionValidationError):
            code = "definition_validation_error"
        return Diagnostic(
            severity=DiagnosticSeverity.ERROR,
            code=code,
            message=str(exc),
            definition_type=definition_type,
            source=origin.source.value,
            location=origin.label,
            details=getattr(exc, "details", {}),
        )
