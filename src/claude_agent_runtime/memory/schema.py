from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

from .._frontmatter import parse_frontmatter_document
from ..definitions import MemoryScope
from ..errors import DefinitionValidationError
from .models import MemoryEntry, ResolvedMemoryScope

MEMORY_SCHEMA_VERSION = "memory.v2"
LONG_TERM_MANIFEST_KIND = "long_term"
AGENT_MANIFEST_KIND = "agent"
SESSION_MANIFEST_KIND = "session"
CONSOLIDATION_MANIFEST_KIND = "consolidation"

REQUIRED_ARTIFACT_FIELDS = frozenset(
    {
        "memory_kind",
        "scope",
        "namespace",
        "retention",
        "source_pathway",
        "created_at",
        "last_confirmed_at",
        "tags",
    }
)
OPTIONAL_ARTIFACT_FIELDS = frozenset(
    {
        "agent_namespace",
        "source_message_ids",
        "supersedes",
        "confidence",
        "summary",
        "token_estimate",
        "stale_after",
        "conflict_key",
        "contested",
    }
)
ARTIFACT_FIELD_VOCABULARY = REQUIRED_ARTIFACT_FIELDS | OPTIONAL_ARTIFACT_FIELDS

DEFAULT_MEMORY_KIND = "note"
DEFAULT_NAMESPACE = "shared"
DEFAULT_RETENTION = "durable_until_superseded"
DEFAULT_SOURCE_PATHWAY = "rule"


@dataclass(frozen=True, slots=True)
class ParsedMemoryArtifact:
    title: str
    content: str
    metadata: dict[str, Any]
    errors: tuple[str, ...] = ()

    @property
    def valid(self) -> bool:
        return not self.errors


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_memory_artifact_metadata(
    entry: MemoryEntry,
    *,
    context: ResolvedMemoryScope,
    namespace: str = DEFAULT_NAMESPACE,
    source_pathway: str | None = None,
) -> dict[str, Any]:
    raw_metadata = dict(entry.metadata)
    if "source" in raw_metadata and "source_pathway" not in raw_metadata:
        raw_metadata["source_pathway"] = raw_metadata.pop("source")
    source = str(source_pathway or raw_metadata.get("source_pathway") or DEFAULT_SOURCE_PATHWAY).strip()
    timestamp = utc_now_iso()
    raw_metadata.setdefault("memory_kind", DEFAULT_MEMORY_KIND)
    raw_metadata.setdefault("scope", context.scope.value)
    raw_metadata.setdefault("namespace", namespace)
    raw_metadata.setdefault("retention", DEFAULT_RETENTION)
    raw_metadata.setdefault("source_pathway", source)
    raw_metadata.setdefault("created_at", timestamp)
    raw_metadata.setdefault("last_confirmed_at", timestamp)
    raw_metadata.setdefault("tags", [])
    normalized, _ = normalize_memory_artifact_metadata(raw_metadata, context=context)
    return normalized


def normalize_memory_artifact_metadata(
    metadata: Mapping[str, Any],
    *,
    context: ResolvedMemoryScope,
    fallback_created_at: str | None = None,
) -> tuple[dict[str, Any], tuple[str, ...]]:
    raw = dict(metadata)
    if "source" in raw and "source_pathway" not in raw:
        raw["source_pathway"] = raw.pop("source")

    errors: list[str] = []
    fallback_timestamp = fallback_created_at or utc_now_iso()

    scope_value = raw.get("scope", context.scope.value)
    if isinstance(scope_value, MemoryScope):
        normalized_scope = scope_value.value
    elif isinstance(scope_value, str) and scope_value.strip() in {scope.value for scope in MemoryScope}:
        normalized_scope = scope_value.strip()
    else:
        normalized_scope = context.scope.value
        errors.append("Invalid 'scope' field")

    namespace = raw.get("namespace", DEFAULT_NAMESPACE)
    if not isinstance(namespace, str) or not namespace.strip():
        namespace = DEFAULT_NAMESPACE
        errors.append("Invalid 'namespace' field")
    else:
        namespace = namespace.strip()

    normalized: dict[str, Any] = {
        "memory_kind": _coerce_required_string(raw.get("memory_kind", DEFAULT_MEMORY_KIND), "memory_kind", errors),
        "scope": normalized_scope,
        "namespace": namespace,
        "retention": _coerce_required_string(raw.get("retention", DEFAULT_RETENTION), "retention", errors),
        "source_pathway": _coerce_required_string(
            raw.get("source_pathway", DEFAULT_SOURCE_PATHWAY),
            "source_pathway",
            errors,
        ),
        "created_at": _coerce_timestamp(raw.get("created_at", fallback_timestamp), "created_at", errors),
        "last_confirmed_at": _coerce_timestamp(
            raw.get("last_confirmed_at", fallback_timestamp),
            "last_confirmed_at",
            errors,
        ),
        "tags": _coerce_string_list(raw.get("tags", ()), "tags", errors),
    }

    agent_namespace = raw.get("agent_namespace")
    if agent_namespace is None or agent_namespace == "":
        normalized["agent_namespace"] = None
    elif isinstance(agent_namespace, str):
        normalized["agent_namespace"] = agent_namespace.strip()
    else:
        normalized["agent_namespace"] = None
        errors.append("Invalid 'agent_namespace' field")

    for field_name in ("source_message_ids", "supersedes"):
        value = raw.get(field_name)
        if value is None:
            continue
        normalized[field_name] = _coerce_string_list(value, field_name, errors)

    if "confidence" in raw and raw["confidence"] is not None:
        confidence = raw["confidence"]
        if isinstance(confidence, (int, float)):
            normalized["confidence"] = float(confidence)
        else:
            errors.append("Invalid 'confidence' field")

    if "summary" in raw and raw["summary"] is not None:
        summary = raw["summary"]
        if isinstance(summary, str) and summary.strip():
            normalized["summary"] = summary.strip()
        else:
            errors.append("Invalid 'summary' field")

    if "token_estimate" in raw and raw["token_estimate"] is not None:
        token_estimate = raw["token_estimate"]
        if isinstance(token_estimate, int) and token_estimate >= 0:
            normalized["token_estimate"] = token_estimate
        else:
            errors.append("Invalid 'token_estimate' field")

    if "stale_after" in raw and raw["stale_after"] is not None:
        normalized["stale_after"] = _coerce_timestamp(raw["stale_after"], "stale_after", errors)

    for field_name in ("conflict_key",):
        value = raw.get(field_name)
        if value is None:
            continue
        if isinstance(value, str) and value.strip():
            normalized[field_name] = value.strip()
        else:
            errors.append(f"Invalid '{field_name}' field")

    if "contested" in raw and raw["contested"] is not None:
        contested = raw["contested"]
        if isinstance(contested, bool):
            normalized["contested"] = contested
        else:
            errors.append("Invalid 'contested' field")

    return normalized, tuple(errors)


def parse_memory_artifact(
    text: str,
    *,
    default_title: str,
    context: ResolvedMemoryScope,
    fallback_created_at: str | None = None,
) -> ParsedMemoryArtifact:
    try:
        frontmatter, body = parse_frontmatter_document(text)
    except (DefinitionValidationError, yaml.YAMLError) as exc:
        return ParsedMemoryArtifact(
            title=default_title,
            content="",
            metadata={},
            errors=(str(exc),),
        )

    title, content = _extract_title_and_body(default_title, body)
    normalized, errors = normalize_memory_artifact_metadata(
        frontmatter,
        context=context,
        fallback_created_at=fallback_created_at,
    )
    if not content.strip():
        errors = (*errors, "Memory artifact body is empty")
    return ParsedMemoryArtifact(
        title=title,
        content=content.strip(),
        metadata=normalized,
        errors=tuple(errors),
    )


def serialize_memory_artifact(title: str, content: str, metadata: Mapping[str, Any]) -> str:
    frontmatter = {
        key: metadata[key]
        for key in (
            "memory_kind",
            "scope",
            "namespace",
            "agent_namespace",
            "retention",
            "source_pathway",
            "source_message_ids",
            "created_at",
            "last_confirmed_at",
            "supersedes",
            "tags",
            "confidence",
            "summary",
            "token_estimate",
            "stale_after",
            "conflict_key",
            "contested",
        )
        if key in metadata and metadata[key] is not None
    }
    raw_frontmatter = yaml.safe_dump(frontmatter, allow_unicode=False, sort_keys=False).strip()
    normalized_title = title.strip() or "Memory note"
    normalized_content = content.strip()
    return f"---\n{raw_frontmatter}\n---\n# {normalized_title}\n\n{normalized_content}\n"


def build_manifest_envelope(
    *,
    manifest_kind: str,
    boundary_scope: MemoryScope,
    payload_key: str,
    payload: Sequence[Mapping[str, Any]],
    stats: Mapping[str, Any] | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    merged_stats = {
        "entry_count": len(payload),
        "stale_entry_count": 0,
    }
    if stats is not None:
        merged_stats.update(dict(stats))
    return {
        "schema_version": MEMORY_SCHEMA_VERSION,
        "manifest_kind": manifest_kind,
        "boundary_scope": boundary_scope.value,
        "generated_at": generated_at or utc_now_iso(),
        "stats": merged_stats,
        payload_key: list(payload),
    }


def content_fingerprint(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:12]


def summarize_content(content: str, *, limit: int = 160) -> str:
    summary = " ".join(content.strip().split())
    if len(summary) <= limit:
        return summary
    return summary[: limit - 3].rstrip() + "..."


def estimate_token_count(text: str) -> int:
    normalized = " ".join(text.split())
    return max(1, (len(normalized) + 3) // 4)


def file_timestamp_iso(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00",
        "Z",
    )


def _coerce_required_string(value: Any, field_name: str, errors: list[str]) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    errors.append(f"Missing or invalid '{field_name}' field")
    return str(value).strip() if value is not None else ""


def _coerce_string_list(value: Any, field_name: str, errors: list[str]) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        cleaned = value.strip()
        return [cleaned] if cleaned else []
    if isinstance(value, (list, tuple)):
        result: list[str] = []
        for item in value:
            if isinstance(item, str) and item.strip():
                result.append(item.strip())
            else:
                errors.append(f"Invalid '{field_name}' list item")
        return result
    errors.append(f"Invalid '{field_name}' field")
    return []


def _coerce_timestamp(value: Any, field_name: str, errors: list[str]) -> str:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    if isinstance(value, str) and value.strip():
        candidate = value.strip()
        try:
            datetime.fromisoformat(candidate.replace("Z", "+00:00"))
            return candidate
        except ValueError:
            errors.append(f"Invalid '{field_name}' timestamp")
            return candidate
    errors.append(f"Missing or invalid '{field_name}' field")
    return utc_now_iso()


def _extract_title_and_body(default_title: str, body: str) -> tuple[str, str]:
    lines = body.splitlines()
    title = default_title.strip() or "Memory note"
    body_lines = lines
    while body_lines and not body_lines[0].strip():
        body_lines = body_lines[1:]
    if body_lines and body_lines[0].startswith("# "):
        title = body_lines[0][2:].strip() or title
        body_lines = body_lines[1:]
        while body_lines and not body_lines[0].strip():
            body_lines = body_lines[1:]
    return title, "\n".join(body_lines).strip()
