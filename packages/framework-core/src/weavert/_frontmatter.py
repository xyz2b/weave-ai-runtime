from __future__ import annotations

import re
from typing import Any

import yaml

from .errors import DefinitionValidationError


FRONTMATTER_BOUNDARY = re.compile(r"^---\s*$", re.MULTILINE)


def parse_frontmatter_document(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---"):
        return {}, text

    matches = list(FRONTMATTER_BOUNDARY.finditer(text))
    if len(matches) < 2:
        raise DefinitionValidationError("Unterminated YAML frontmatter block")

    start, end = matches[0], matches[1]
    raw_frontmatter = text[start.end() : end.start()]
    body = text[end.end() :].lstrip("\n")
    parsed = yaml.safe_load(raw_frontmatter) or {}
    if not isinstance(parsed, dict):
        raise DefinitionValidationError("YAML frontmatter must decode to an object")
    return parsed, body


def extract_markdown_description(markdown: str) -> str:
    for line in markdown.splitlines():
        candidate = line.strip()
        if not candidate:
            continue
        if candidate.startswith("#"):
            candidate = candidate.lstrip("#").strip()
        if candidate:
            return candidate
    return "No description provided."


def coerce_string_list(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        parts = [part.strip() for part in re.split(r"[,\n]", value) if part.strip()]
        return tuple(parts)
    if isinstance(value, list):
        return tuple(str(item).strip() for item in value if str(item).strip())
    raise DefinitionValidationError("Expected a string or list of strings")


def coerce_bool(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "yes", "1", "on"}:
            return True
        if lowered in {"false", "no", "0", "off"}:
            return False
    raise DefinitionValidationError("Expected a boolean-compatible value")


def coerce_mapping(value: Any, *, field_name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    raise DefinitionValidationError(f"Expected '{field_name}' to be an object")

