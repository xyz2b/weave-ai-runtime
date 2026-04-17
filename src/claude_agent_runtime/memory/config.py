from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import yaml

_SUPPORTED_MEMORY_FACT_TYPES = frozenset(
    {
        "agent_workflow",
        "preference",
        "project_convention",
        "session_continuity",
        "session_thread",
        "sensitive_value",
        "topic_memory",
        "transient_task",
        "workflow_command",
    }
)
_FACT_TYPE_ALIASES = {
    "secret": "sensitive_value",
    "topic": "topic_memory",
    "convention": "project_convention",
}
_ALLOWED_ROUTING_TARGETS = {
    "preference": frozenset({"long_term.preferences"}),
    "project_convention": frozenset({"long_term.conventions"}),
    "workflow_command": frozenset({"long_term.conventions"}),
    "topic_memory": frozenset({"long_term.topics"}),
    "agent_workflow": frozenset({"agent_namespace"}),
    "session_thread": frozenset({"session"}),
    "session_continuity": frozenset({"session"}),
}
_CONFIG_FILENAMES = ("config.yaml", "config.yml")


@dataclass(frozen=True, slots=True)
class MemoryRetrievalConfig:
    max_results: int | None = None
    embedding_enabled: bool | None = None
    llm_rerank: str | None = None
    prefer_tags: tuple[str, ...] = ()
    suppress_tags: tuple[str, ...] = ()
    stale_decay_days: int | None = None


@dataclass(frozen=True, slots=True)
class MemoryExtractionConfig:
    background_synthesis: bool | None = None
    always_capture: tuple[str, ...] = ()
    never_capture: tuple[str, ...] = ()
    routing: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class MemorySessionRefreshConfig:
    token_growth_threshold: int = 4000
    tool_call_threshold: int = 8
    turn_threshold: int = 6


@dataclass(frozen=True, slots=True)
class MemorySessionConfig:
    refresh: MemorySessionRefreshConfig = field(default_factory=MemorySessionRefreshConfig)


@dataclass(frozen=True, slots=True)
class MemoryConsolidationConfig:
    enable_background: bool = True
    min_closed_sessions: int = 4
    min_hours_since_last_run: int = 12
    backlog_threshold: int = 4


@dataclass(frozen=True, slots=True)
class MemoryRuntimeConfig:
    retrieval: MemoryRetrievalConfig = field(default_factory=MemoryRetrievalConfig)
    extraction: MemoryExtractionConfig = field(default_factory=MemoryExtractionConfig)
    session_memory: MemorySessionConfig = field(default_factory=MemorySessionConfig)
    consolidation: MemoryConsolidationConfig = field(default_factory=MemoryConsolidationConfig)


@dataclass(frozen=True, slots=True)
class ResolvedMemoryConfig:
    config: MemoryRuntimeConfig
    warnings: tuple[str, ...] = ()
    source_path: Path | None = None


def resolve_memory_config(
    *,
    memory_root: Path,
    override: Mapping[str, Any] | MemoryRuntimeConfig | None = None,
) -> ResolvedMemoryConfig:
    warnings: list[str] = []
    source_path: Path | None = None

    merged_payload: dict[str, Any] = {}
    if isinstance(override, Mapping):
        merged_payload = _deep_merge(merged_payload, dict(override))
    elif isinstance(override, MemoryRuntimeConfig):
        return ResolvedMemoryConfig(config=override, warnings=(), source_path=None)

    for candidate in _config_paths(memory_root):
        if not candidate.exists() or not candidate.is_file():
            continue
        source_path = candidate
        try:
            loaded = yaml.safe_load(candidate.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            warnings.append(f"Invalid memory config YAML at {candidate.name}: {exc}")
            break
        if loaded is None:
            break
        if not isinstance(loaded, dict):
            warnings.append(f"Invalid memory config root at {candidate.name}: expected a mapping")
            break
        payload = loaded.get("memory", loaded)
        if not isinstance(payload, dict):
            warnings.append(f"Invalid memory config root at {candidate.name}: expected 'memory' to be a mapping")
            break
        merged_payload = _deep_merge(merged_payload, payload)
        break

    config = parse_memory_config_payload(merged_payload, warnings=warnings)
    return ResolvedMemoryConfig(
        config=config,
        warnings=tuple(dict.fromkeys(warnings)),
        source_path=source_path,
    )


def parse_memory_config_payload(
    payload: Mapping[str, Any] | None,
    *,
    warnings: list[str] | None = None,
) -> MemoryRuntimeConfig:
    warning_sink = warnings if warnings is not None else []
    payload = payload or {}

    retrieval = _parse_retrieval_config(_mapping(payload.get("retrieval")), warnings=warning_sink)
    extraction = _parse_extraction_config(_mapping(payload.get("extraction")), warnings=warning_sink)
    session_memory = _parse_session_config(_mapping(payload.get("session_memory")), warnings=warning_sink)
    consolidation = _parse_consolidation_config(_mapping(payload.get("consolidation")), warnings=warning_sink)
    return MemoryRuntimeConfig(
        retrieval=retrieval,
        extraction=extraction,
        session_memory=session_memory,
        consolidation=consolidation,
    )


def describe_memory_config(resolved: ResolvedMemoryConfig) -> dict[str, Any]:
    config = resolved.config
    return {
        "source_path": str(resolved.source_path) if resolved.source_path is not None else None,
        "warnings": list(resolved.warnings),
        "retrieval": {
            "max_results": config.retrieval.max_results,
            "embedding_enabled": config.retrieval.embedding_enabled,
            "llm_rerank": config.retrieval.llm_rerank,
            "prefer_tags": list(config.retrieval.prefer_tags),
            "suppress_tags": list(config.retrieval.suppress_tags),
            "stale_decay_days": config.retrieval.stale_decay_days,
        },
        "extraction": {
            "background_synthesis": config.extraction.background_synthesis,
            "always_capture": list(config.extraction.always_capture),
            "never_capture": list(config.extraction.never_capture),
            "routing": dict(config.extraction.routing),
        },
        "session_memory": {
            "refresh": {
                "token_growth_threshold": config.session_memory.refresh.token_growth_threshold,
                "tool_call_threshold": config.session_memory.refresh.tool_call_threshold,
                "turn_threshold": config.session_memory.refresh.turn_threshold,
            }
        },
        "consolidation": {
            "enable_background": config.consolidation.enable_background,
            "min_closed_sessions": config.consolidation.min_closed_sessions,
            "min_hours_since_last_run": config.consolidation.min_hours_since_last_run,
            "backlog_threshold": config.consolidation.backlog_threshold,
        },
    }


def _parse_retrieval_config(payload: Mapping[str, Any], *, warnings: list[str]) -> MemoryRetrievalConfig:
    llm_rerank = _optional_string(payload.get("llm_rerank"))
    if llm_rerank is not None and llm_rerank not in {"auto", "enabled", "disabled"}:
        warnings.append("Ignoring memory.retrieval.llm_rerank: expected one of auto/enabled/disabled")
        llm_rerank = None
    return MemoryRetrievalConfig(
        max_results=_positive_int(payload.get("max_results"), "memory.retrieval.max_results", warnings),
        embedding_enabled=_optional_bool(
            payload.get("embedding_enabled"),
            "memory.retrieval.embedding_enabled",
            warnings,
        ),
        llm_rerank=llm_rerank,
        prefer_tags=_string_list(payload.get("prefer_tags"), "memory.retrieval.prefer_tags", warnings),
        suppress_tags=_string_list(payload.get("suppress_tags"), "memory.retrieval.suppress_tags", warnings),
        stale_decay_days=_positive_int(payload.get("stale_decay_days"), "memory.retrieval.stale_decay_days", warnings),
    )


def _parse_extraction_config(payload: Mapping[str, Any], *, warnings: list[str]) -> MemoryExtractionConfig:
    return MemoryExtractionConfig(
        background_synthesis=_optional_bool(
            payload.get("background_synthesis"),
            "memory.extraction.background_synthesis",
            warnings,
        ),
        always_capture=_fact_type_list(payload.get("always_capture"), "memory.extraction.always_capture", warnings),
        never_capture=_fact_type_list(payload.get("never_capture"), "memory.extraction.never_capture", warnings),
        routing=_routing_overrides(payload.get("routing"), warnings=warnings),
    )


def _parse_session_config(payload: Mapping[str, Any], *, warnings: list[str]) -> MemorySessionConfig:
    refresh_payload = _mapping(payload.get("refresh"))
    return MemorySessionConfig(
        refresh=MemorySessionRefreshConfig(
            token_growth_threshold=_positive_int(
                refresh_payload.get("token_growth_threshold"),
                "memory.session_memory.refresh.token_growth_threshold",
                warnings,
                default=4000,
            ),
            tool_call_threshold=_positive_int(
                refresh_payload.get("tool_call_threshold"),
                "memory.session_memory.refresh.tool_call_threshold",
                warnings,
                default=8,
            ),
            turn_threshold=_positive_int(
                refresh_payload.get("turn_threshold"),
                "memory.session_memory.refresh.turn_threshold",
                warnings,
                default=6,
            ),
        )
    )


def _parse_consolidation_config(payload: Mapping[str, Any], *, warnings: list[str]) -> MemoryConsolidationConfig:
    return MemoryConsolidationConfig(
        enable_background=_optional_bool(
            payload.get("enable_background"),
            "memory.consolidation.enable_background",
            warnings,
            default=True,
        ),
        min_closed_sessions=_positive_int(
            payload.get("min_closed_sessions"),
            "memory.consolidation.min_closed_sessions",
            warnings,
            default=4,
        ),
        min_hours_since_last_run=_positive_int(
            payload.get("min_hours_since_last_run"),
            "memory.consolidation.min_hours_since_last_run",
            warnings,
            default=12,
        ),
        backlog_threshold=_positive_int(
            payload.get("backlog_threshold"),
            "memory.consolidation.backlog_threshold",
            warnings,
            default=4,
        ),
    )


def _routing_overrides(value: Any, *, warnings: list[str]) -> dict[str, str]:
    payload = _mapping(value)
    overrides: dict[str, str] = {}
    for raw_fact_type, raw_target in payload.items():
        if not isinstance(raw_fact_type, str) or not raw_fact_type.strip():
            warnings.append("Ignoring invalid memory.extraction.routing key: expected a non-empty string")
            continue
        fact_type = _normalize_fact_type(raw_fact_type)
        if fact_type is None:
            warnings.append(f"Ignoring unsupported memory.extraction.routing key: {raw_fact_type!r}")
            continue
        target = _optional_string(raw_target)
        if target is None:
            warnings.append(f"Ignoring memory.extraction.routing.{raw_fact_type}: expected a string target")
            continue
        allowed_targets = _ALLOWED_ROUTING_TARGETS.get(fact_type, frozenset())
        if target not in allowed_targets:
            warnings.append(
                f"Ignoring unsafe routing override for {fact_type}: {target!r} is outside the safe target set"
            )
            continue
        overrides[fact_type] = target
    return overrides


def _fact_type_list(value: Any, field_name: str, warnings: list[str]) -> tuple[str, ...]:
    values = _string_list(value, field_name, warnings)
    normalized: list[str] = []
    for item in values:
        fact_type = _normalize_fact_type(item)
        if fact_type is None:
            warnings.append(f"Ignoring unsupported {field_name} value: {item!r}")
            continue
        if fact_type not in normalized:
            normalized.append(fact_type)
    return tuple(normalized)


def _normalize_fact_type(value: str) -> str | None:
    candidate = value.strip()
    normalized = _FACT_TYPE_ALIASES.get(candidate, candidate)
    return normalized if normalized in _SUPPORTED_MEMORY_FACT_TYPES else None


def _positive_int(value: Any, field_name: str, warnings: list[str], *, default: int | None = None) -> int | None:
    if value is None:
        return default
    if isinstance(value, bool):
        warnings.append(f"Ignoring {field_name}: expected a positive integer")
        return default
    if isinstance(value, int) and value > 0:
        return value
    warnings.append(f"Ignoring {field_name}: expected a positive integer")
    return default


def _optional_bool(
    value: Any,
    field_name: str,
    warnings: list[str],
    *,
    default: bool | None = None,
) -> bool | None:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    warnings.append(f"Ignoring {field_name}: expected a boolean")
    return default


def _string_list(value: Any, field_name: str, warnings: list[str]) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        warnings.append(f"Ignoring {field_name}: expected a list of strings")
        return ()
    values: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            warnings.append(f"Ignoring invalid {field_name} entry: expected a non-empty string")
            continue
        normalized = item.strip()
        if normalized not in values:
            values.append(normalized)
    return tuple(values)


def _optional_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _config_paths(memory_root: Path) -> tuple[Path, ...]:
    return tuple(memory_root / filename for filename in _CONFIG_FILENAMES)


def _deep_merge(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        existing = merged.get(key)
        if isinstance(existing, Mapping) and isinstance(value, Mapping):
            merged[key] = _deep_merge(existing, value)
            continue
        merged[key] = value
    return merged
