from __future__ import annotations

import re
from fnmatch import fnmatch
from pathlib import Path, PurePath
from typing import TYPE_CHECKING, Any, Iterable, Mapping, Sequence

from .contracts import (
    MessageRole,
    PromptContextEnvelope,
    RuntimeMessage,
    RuntimePrivateContext,
    ToolResultBlock,
    compatibility_runtime_context_snapshot,
    merge_runtime_private_context,
    prompt_context_from_legacy_runtime_context,
)
from .definitions import (
    DefinitionSource,
    InvocationCapabilityView,
    InvocationDefinition,
    InvocationDiagnostics,
    InvocationExecutionPolicy,
    InvocationHiddenReason,
    InvocationPathMatchState,
    InvocationResolutionContext,
    InvocationSourceKind,
    InvocationTargetKind,
    InvocationVisibilityPolicy,
    ResolvedInvocation,
    ResolvedInvocationCatalog,
    SkillDefinition,
)
from .execution_policy import policy_allows_skill, policy_state_from_metadata

if TYPE_CHECKING:
    from .registries.skill_registry import SkillRegistry

_TRAILING_PATH_PUNCTUATION = "\"'`,:;!?)]}>"
_LEADING_PATH_PUNCTUATION = "\"'`([<{"


class SkillInvocationProvider:
    name = "skills"

    def __init__(
        self,
        registry: "SkillRegistry",
        *,
        skill_resolver: Any | None = None,
    ) -> None:
        self._registry = registry
        self._skill_resolver = skill_resolver

    def list_invocations(self) -> tuple[InvocationDefinition, ...]:
        return tuple(self._to_invocation(skill) for skill in self._registry.definitions())

    def list_invocations_for_context(
        self,
        context: InvocationResolutionContext,
    ) -> tuple[InvocationDefinition, ...]:
        if self._skill_resolver is None:
            return self.list_invocations()
        return tuple(
            self._to_invocation(skill)
            for skill in self._skill_resolver.resolve(context)
        )

    def _to_invocation(self, skill: SkillDefinition) -> InvocationDefinition:
        surface_hints: dict[str, Any] = {}
        if skill.when_to_use:
            surface_hints["when_to_use"] = skill.when_to_use
        if skill.argument_names:
            surface_hints["argument_names"] = tuple(skill.argument_names)
        activation_enabled = True
        registry_skill = self._registry.get(skill.name)
        if registry_skill is not None:
            activation_enabled = self._registry.is_active(skill.name)
        metadata = {
            "activation_enabled": activation_enabled,
            "frontmatter": dict(skill.metadata.get("raw_frontmatter", {})),
            "skill_definition": skill,
            "skill_root": str(skill.origin.root) if skill.origin.root is not None else None,
            "skill_source": skill.origin.source.value,
            "dynamic_root": skill.metadata.get("dynamic_root"),
        }
        source_kind = (
            InvocationSourceKind.BUILTIN_SKILL
            if skill.origin.source == DefinitionSource.BUNDLED
            else InvocationSourceKind.SKILL_DIR
        )
        return InvocationDefinition(
            name=skill.name,
            source_kind=source_kind,
            display_name=skill.display_name,
            description=skill.description,
            argument_hint=skill.argument_hint,
            visibility_policy=InvocationVisibilityPolicy(
                user_invocable=skill.user_invocable,
                model_invocable=not skill.disable_model_invocation,
                paths=skill.paths,
                surface_hints=surface_hints,
            ),
            execution_policy=InvocationExecutionPolicy(
                target_kind=InvocationTargetKind.SKILL,
                target_name=skill.name,
                context=skill.execution_context.value,
                allowed_tools=skill.allowed_tools,
                agent=skill.agent,
                model=skill.model,
                effort=skill.effort,
                hooks=skill.hooks,
            ),
            metadata=metadata,
            origin=skill.origin,
        )


class StaticInvocationProvider:
    def __init__(
        self,
        name: str,
        definitions: Sequence[InvocationDefinition] = (),
    ) -> None:
        self.name = name
        self._definitions = tuple(definitions)

    def list_invocations(self) -> tuple[InvocationDefinition, ...]:
        return self._definitions


class SlashCommandInvocationProvider(StaticInvocationProvider):
    def __init__(self, definitions: Sequence[InvocationDefinition] = ()) -> None:
        super().__init__(name="slash_commands", definitions=definitions)


class PluginCommandInvocationProvider(StaticInvocationProvider):
    def __init__(self, definitions: Sequence[InvocationDefinition] = ()) -> None:
        super().__init__(name="plugin_commands", definitions=definitions)


class McpPromptInvocationProvider(StaticInvocationProvider):
    def __init__(self, definitions: Sequence[InvocationDefinition] = ()) -> None:
        super().__init__(name="mcp_prompts", definitions=definitions)


def build_invocation_resolution_context(
    *,
    session_id: str,
    turn_id: str | None,
    cwd: str | Path,
    messages: Sequence[RuntimeMessage],
    prompt_context: PromptContextEnvelope | None = None,
    private_context: RuntimePrivateContext | Mapping[str, object] | None = None,
    runtime_context: Mapping[str, object] | None = None,
) -> InvocationResolutionContext:
    resolved_cwd = Path(cwd).resolve()
    resolved_prompt_context = _merge_prompt_context(
        prompt_context_from_legacy_runtime_context(runtime_context),
        prompt_context,
    )
    resolved_private_context = merge_runtime_private_context(
        private_context,
        runtime_context,
    )
    context_metadata = _invocation_context_metadata(
        prompt_context=resolved_prompt_context,
        private_context=resolved_private_context,
        runtime_context=runtime_context,
    )
    latest_prompt = _latest_prompt_message(messages)
    prompt_paths = set(_coerce_string_sequence(context_metadata.get("prompt_paths")))
    prompt_paths.update(_coerce_string_sequence(_metadata_values(latest_prompt, "prompt_paths")))
    if latest_prompt is not None:
        prompt_paths.update(_extract_path_tokens(latest_prompt.text))

    attachments = set(_coerce_string_sequence(context_metadata.get("attachments")))
    attachments.update(_coerce_string_sequence(_metadata_values(latest_prompt, "attachments")))
    if resolved_prompt_context.attachments:
        attachments.update(
            attachment.path
            for attachment in resolved_prompt_context.attachments
            if getattr(attachment, "path", None)
        )
    if latest_prompt is not None:
        attachments.update(
            attachment.path
            for attachment in latest_prompt.attachments
            if getattr(attachment, "path", None)
        )

    workspace_roots = {resolved_cwd}
    workspace_roots.update(_coerce_path_sequence(context_metadata.get("workspace_roots")))
    workspace_roots.update(_coerce_path_sequence(_metadata_values(latest_prompt, "workspace_roots")))

    observed_paths = set(_coerce_string_sequence(context_metadata.get("observed_paths")))
    for message in messages:
        observed_paths.update(_coerce_string_sequence(_metadata_values(message, "observed_paths")))

    working_set = set(_coerce_string_sequence(context_metadata.get("working_set")))
    working_set.update(_coerce_string_sequence(context_metadata.get("working_set_paths")))
    working_set.update(_coerce_string_sequence(_metadata_values(latest_prompt, "working_set")))
    working_set.update(_coerce_string_sequence(_metadata_values(latest_prompt, "working_set_paths")))

    return InvocationResolutionContext(
        session_id=session_id,
        turn_id=turn_id,
        cwd=resolved_cwd,
        prompt_paths=tuple(sorted(prompt_paths)),
        attachments=tuple(sorted(attachments)),
        workspace_roots=tuple(
            Path(path)
            for path in sorted((str(path) for path in workspace_roots))
        ),
        observed_paths=tuple(sorted(observed_paths)),
        working_set=tuple(sorted(working_set)),
        metadata=context_metadata,
    )


def _invocation_context_metadata(
    *,
    prompt_context: PromptContextEnvelope | None,
    private_context: RuntimePrivateContext | Mapping[str, object] | None,
    runtime_context: Mapping[str, object] | None,
) -> dict[str, object]:
    metadata = compatibility_runtime_context_snapshot(
        runtime_context,
        prompt_context=prompt_context,
        private_context=private_context,
    )
    if prompt_context is not None:
        metadata.update(_mapping_metadata(prompt_context.extensions))
    return metadata


def _merge_prompt_context(
    compat_prompt_context: PromptContextEnvelope,
    explicit_prompt_context: PromptContextEnvelope | None,
) -> PromptContextEnvelope:
    if explicit_prompt_context is None:
        return compat_prompt_context
    session_hints = dict(compat_prompt_context.session_hints)
    session_hints.update(explicit_prompt_context.session_hints)
    extensions = dict(compat_prompt_context.extensions)
    extensions.update(explicit_prompt_context.extensions)
    return PromptContextEnvelope(
        memory_fragments=compat_prompt_context.memory_fragments + explicit_prompt_context.memory_fragments,
        hook_fragments=compat_prompt_context.hook_fragments + explicit_prompt_context.hook_fragments,
        compaction_fragments=(
            compat_prompt_context.compaction_fragments + explicit_prompt_context.compaction_fragments
        ),
        attachments=compat_prompt_context.attachments + explicit_prompt_context.attachments,
        session_hints=session_hints,
        compaction_summary=(
            explicit_prompt_context.compaction_summary
            if explicit_prompt_context.compaction_summary is not None
            else compat_prompt_context.compaction_summary
        ),
        compaction_boundary=(
            explicit_prompt_context.compaction_boundary
            if explicit_prompt_context.compaction_boundary is not None
            else compat_prompt_context.compaction_boundary
        ),
        compaction_continuation=(
            explicit_prompt_context.compaction_continuation
            if explicit_prompt_context.compaction_continuation is not None
            else compat_prompt_context.compaction_continuation
        ),
        extensions=extensions,
    )


def _mapping_metadata(value: Mapping[str, object] | None) -> dict[str, object]:
    if value is None:
        return {}
    return {str(key): inner for key, inner in value.items()}


def resolve_invocation_catalog(
    entries: Sequence[InvocationDefinition],
    context: InvocationResolutionContext,
) -> ResolvedInvocationCatalog:
    visible: list[ResolvedInvocation] = []
    hidden: list[ResolvedInvocation] = []
    for definition in entries:
        path_state, matched_paths = _evaluate_path_state(definition, context)
        activation_enabled = bool(definition.metadata.get("activation_enabled", True))
        visible_now = activation_enabled and path_state == InvocationPathMatchState.MATCHED
        policy_visible, policy_narrowing = _policy_visibility(definition, context)
        if visible_now and not policy_visible:
            visible_now = False
        hidden_reason = _hidden_reason(
            activation_enabled=activation_enabled,
            path_state=path_state,
            policy_visible=policy_visible,
        )
        user_invocable = visible_now and definition.visibility_policy.user_invocable
        model_invocable = visible_now and definition.visibility_policy.model_invocable
        diagnostics = InvocationDiagnostics(
            name=definition.name,
            source_kind=definition.source_kind,
            visible=visible_now,
            user_invocable=user_invocable,
            model_invocable=model_invocable,
            hidden_reason=hidden_reason,
            matched_paths=tuple(sorted(set(matched_paths))),
            path_match_state=path_state,
            narrowed_by_policy=_policy_narrowing(definition, policy_narrowing),
            metadata=_diagnostics_metadata(definition),
        )
        resolved = ResolvedInvocation(
            definition=definition,
            capability=InvocationCapabilityView(
                name=definition.name,
                source_kind=definition.source_kind,
                display_name=definition.display_name,
                description=definition.description,
                argument_hint=definition.argument_hint,
                user_invocable=user_invocable,
                model_invocable=model_invocable,
                source_label=definition.origin.label,
                metadata=_capability_metadata(definition),
            ),
            diagnostics=diagnostics,
        )
        if visible_now:
            visible.append(resolved)
        else:
            hidden.append(resolved)
    return ResolvedInvocationCatalog(visible=tuple(visible), hidden=tuple(hidden))


def _evaluate_path_state(
    definition: InvocationDefinition,
    context: InvocationResolutionContext,
) -> tuple[InvocationPathMatchState, tuple[str, ...]]:
    patterns = definition.visibility_policy.paths
    if not patterns:
        return InvocationPathMatchState.MATCHED, ()

    explicit_paths = tuple(
        dict.fromkeys(
            (
                *context.prompt_paths,
                *context.attachments,
                *context.observed_paths,
                *context.working_set,
            )
        )
    )
    matched: list[str] = []
    for candidate in explicit_paths:
        if _matches_path_patterns(
            patterns=patterns,
            candidate=candidate,
            cwd=context.cwd,
            workspace_roots=context.workspace_roots,
        ):
            matched.append(candidate)
    if matched:
        return InvocationPathMatchState.MATCHED, tuple(matched)
    if explicit_paths:
        return InvocationPathMatchState.NOT_MATCHED, ()
    return InvocationPathMatchState.INDETERMINATE, ()


def _hidden_reason(
    *,
    activation_enabled: bool,
    path_state: InvocationPathMatchState,
    policy_visible: bool,
) -> InvocationHiddenReason | None:
    if not activation_enabled:
        return InvocationHiddenReason.INACTIVE
    if path_state == InvocationPathMatchState.NOT_MATCHED:
        return InvocationHiddenReason.PATH_MISMATCH
    if path_state == InvocationPathMatchState.INDETERMINATE:
        return InvocationHiddenReason.PATH_INDETERMINATE
    if not policy_visible:
        return InvocationHiddenReason.POLICY_NARROWED
    return None


def _policy_narrowing(
    definition: InvocationDefinition,
    dynamic_narrowing: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    narrowed: dict[str, Any] = {}
    policy = definition.execution_policy
    if policy is None:
        if dynamic_narrowing:
            narrowed.update(dynamic_narrowing)
        return narrowed
    if policy.allowed_tools:
        narrowed["allowed_tools"] = tuple(policy.allowed_tools)
    if policy.context is not None:
        narrowed["context"] = policy.context
    if policy.agent is not None:
        narrowed["agent"] = policy.agent
    if policy.model is not None:
        narrowed["model"] = policy.model
    if policy.effort is not None:
        narrowed["effort"] = policy.effort
    if policy.hooks:
        narrowed["hooks"] = tuple(sorted(policy.hooks))
    if dynamic_narrowing:
        narrowed.update(dynamic_narrowing)
    return narrowed


def _policy_visibility(
    definition: InvocationDefinition,
    context: InvocationResolutionContext,
) -> tuple[bool, dict[str, Any]]:
    state = policy_state_from_metadata(context.metadata)
    if state is None:
        return True, {}
    skill = definition.metadata.get("skill_definition")
    if not isinstance(skill, SkillDefinition):
        return True, {}
    allowed_skill_names = tuple(skill_definition.name for skill_definition in state.effective.skill_pool)
    narrowed: dict[str, Any] = {"skill_pool": allowed_skill_names}
    if not policy_allows_skill(skill.name, state.effective.skill_pool):
        narrowed["blocked_by"] = "execution_policy.skill_pool"
        return False, narrowed
    return True, narrowed


def _capability_metadata(definition: InvocationDefinition) -> dict[str, Any]:
    metadata: dict[str, Any] = dict(definition.visibility_policy.surface_hints)
    policy = definition.execution_policy
    if policy is not None:
        metadata["target_kind"] = policy.target_kind.value
        metadata["target_name"] = policy.target_name
    provider_name = definition.metadata.get("invocation_provider_name")
    if provider_name is not None:
        metadata["provider_name"] = provider_name
    provider_origin = definition.metadata.get("invocation_provider_origin")
    if provider_origin is not None:
        metadata["provider_origin"] = provider_origin
    provider_owner = definition.metadata.get("invocation_provider_owner")
    if provider_owner is not None:
        metadata["provider_owner"] = provider_owner
    return metadata


def _diagnostics_metadata(definition: InvocationDefinition) -> dict[str, Any]:
    metadata = _capability_metadata(definition)
    metadata["source_label"] = definition.origin.label
    skill_root = definition.metadata.get("skill_root")
    if skill_root is not None:
        metadata["skill_root"] = skill_root
    skill_source = definition.metadata.get("skill_source")
    if skill_source is not None:
        metadata["skill_source"] = skill_source
    dynamic_root = definition.metadata.get("dynamic_root")
    if dynamic_root is not None:
        metadata["dynamic_root"] = dynamic_root
    provider_registration = definition.metadata.get("invocation_provider_registration")
    if provider_registration is not None:
        metadata["provider_registration"] = provider_registration
    return metadata


def _latest_message(
    messages: Sequence[RuntimeMessage],
    role: MessageRole,
) -> RuntimeMessage | None:
    for message in reversed(messages):
        if message.role == role:
            return message
    return None


def _latest_prompt_message(messages: Sequence[RuntimeMessage]) -> RuntimeMessage | None:
    for message in reversed(messages):
        if message.role != MessageRole.USER:
            continue
        if _is_tool_result_replay(message):
            continue
        return message
    return None


def _is_tool_result_replay(message: RuntimeMessage) -> bool:
    if message.metadata.get("tool_results"):
        return True
    return bool(message.content) and all(isinstance(block, ToolResultBlock) for block in message.content)


def _metadata_values(message: RuntimeMessage | None, key: str) -> object:
    if message is None:
        return ()
    return message.metadata.get(key)


def _coerce_path_sequence(value: object) -> tuple[Path, ...]:
    return tuple(Path(item).resolve() for item in _coerce_string_sequence(value))


def _coerce_string_sequence(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        normalized = value.strip()
        return (normalized,) if normalized else ()
    if isinstance(value, Path):
        return (str(value),)
    if isinstance(value, Mapping):
        if "path" in value:
            return _coerce_string_sequence(value["path"])
        return ()
    if isinstance(value, Iterable):
        selected: list[str] = []
        for item in value:
            if isinstance(item, Mapping) and "path" in item:
                selected.extend(_coerce_string_sequence(item["path"]))
                continue
            if item is None:
                continue
            normalized = str(item).strip()
            if normalized:
                selected.append(normalized)
        return tuple(selected)
    normalized = str(value).strip()
    return (normalized,) if normalized else ()


def _matches_path_patterns(
    *,
    patterns: Sequence[str],
    candidate: str,
    cwd: Path,
    workspace_roots: Sequence[Path],
) -> bool:
    variants = _path_variants(candidate=candidate, cwd=cwd, workspace_roots=workspace_roots)
    return any(fnmatch(variant, pattern) for variant in variants for pattern in patterns)


def _path_variants(
    *,
    candidate: str,
    cwd: Path,
    workspace_roots: Sequence[Path],
) -> tuple[str, ...]:
    variants: list[str] = []
    roots = tuple(dict.fromkeys((cwd, *workspace_roots)))
    candidate_path = Path(candidate)
    if candidate_path.is_absolute():
        resolved = candidate_path.resolve()
    else:
        resolved = (cwd / candidate_path).resolve()
    variants.append(_normalize_path_string(str(PurePath(candidate))))
    variants.append(_normalize_path_string(str(resolved)))
    for root in roots:
        try:
            relative = resolved.relative_to(root.resolve())
        except ValueError:
            continue
        variants.append(_normalize_path_string(str(relative)))
    deduped: list[str] = []
    seen: set[str] = set()
    for variant in variants:
        if variant in seen:
            continue
        seen.add(variant)
        deduped.append(variant)
    return tuple(deduped)


def _normalize_path_string(value: str) -> str:
    return str(PurePath(value.replace("\\", "/")))


def _extract_path_tokens(text: str) -> tuple[str, ...]:
    tokens: list[str] = []
    for raw in re.split(r"\s+", text):
        if not raw:
            continue
        token = raw.strip(_TRAILING_PATH_PUNCTUATION).lstrip(_LEADING_PATH_PUNCTUATION)
        if not token or "://" in token:
            continue
        normalized = token.replace("\\", "/")
        if not _looks_like_path(normalized):
            continue
        tokens.append(normalized)
    deduped: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        if token in seen:
            continue
        seen.add(token)
        deduped.append(token)
    return tuple(deduped)


def _looks_like_path(token: str) -> bool:
    if "/" in token:
        return True
    if token.startswith((".", "~")):
        return True
    if "*" in token or "?" in token or "[" in token:
        return True
    if re.fullmatch(r"[A-Za-z0-9_.-]+\.[A-Za-z0-9_.-]+", token):
        return True
    return False


__all__ = [
    "SkillInvocationProvider",
    "SlashCommandInvocationProvider",
    "PluginCommandInvocationProvider",
    "McpPromptInvocationProvider",
    "StaticInvocationProvider",
    "build_invocation_resolution_context",
    "resolve_invocation_catalog",
]
