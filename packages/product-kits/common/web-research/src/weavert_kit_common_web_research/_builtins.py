from __future__ import annotations

from weavert.builtins.definition_helpers import static_semantics
from weavert.definitions import (
    DefinitionOrigin,
    DefinitionSource,
    ToolClassifierInput,
    ToolDefinition,
    ToolPresentationEmphasis,
    ToolRiskLevel,
    ToolTraits,
    ToolUsePresentation,
)

from ._tool_impls import (
    technical_web_fetch_tool,
    technical_web_find_tool,
    technical_web_search_tool,
    validate_technical_web_fetch,
    validate_technical_web_find,
    validate_technical_web_search,
)

CODING_WEB_RESEARCH_TOOLS = (
    "technical_web_search",
    "technical_web_fetch",
    "technical_web_find",
)


def shared_coding_web_research_builtin_tools() -> tuple[ToolDefinition, ...]:
    origin = DefinitionOrigin(DefinitionSource.BUNDLED)
    source_schema = {
        "type": "object",
        "properties": {
            "url": {"type": "string"},
            "title": {"type": "string"},
            "source_handle": {"type": "string"},
            "page_handle": {"type": "string"},
        },
        "additionalProperties": True,
    }
    page_schema = {
        "type": "object",
        "properties": {
            "url": {"type": "string"},
            "title": {"type": "string"},
            "content": {"type": "string"},
            "source_handle": {"type": "string"},
            "page_handle": {"type": "string"},
        },
        "additionalProperties": True,
    }
    return (
        ToolDefinition(
            name="technical_web_search",
            description="Search versioned technical references within explicit domains.",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "domains": {"type": "array", "items": {"type": "string"}},
                    "blocked_domains": {"type": "array", "items": {"type": "string"}},
                    "version": {"type": "string"},
                    "freshness_days": {"type": "integer", "minimum": 0},
                    "recency_days": {"type": "integer", "minimum": 0},
                    "freshness_required": {"type": "boolean"},
                    "provider": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 8},
                },
                "required": ["query", "domains"],
                "additionalProperties": False,
            },
            traits=ToolTraits(read_only=True, concurrency_safe=True),
            semantics=_network_semantics(
                title="Search technical web sources",
                operation="technical_web_search",
                summary_prefix="Search technical web sources",
                subtitle_key="query",
            ),
            validate_input=validate_technical_web_search,
            execute=technical_web_search_tool,
            origin=origin,
        ),
        ToolDefinition(
            name="technical_web_fetch",
            description="Inspect a technical source and preserve auditable source metadata.",
            input_schema={
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "source": source_schema,
                    "version": {"type": "string"},
                    "timeout_ms": {"type": "integer", "minimum": 1},
                    "max_chars": {"type": "integer", "minimum": 500, "maximum": 32000},
                },
                "additionalProperties": False,
            },
            traits=ToolTraits(read_only=True, concurrency_safe=True),
            semantics=_network_semantics(
                title="Inspect technical web source",
                operation="technical_web_fetch",
                summary_prefix="Inspect technical web source",
                subtitle_key="url",
            ),
            validate_input=validate_technical_web_fetch,
            execute=technical_web_fetch_tool,
            origin=origin,
        ),
        ToolDefinition(
            name="technical_web_find",
            description="Find exact local evidence inside an inspected technical source.",
            input_schema={
                "type": "object",
                "properties": {
                    "page": page_schema,
                    "pattern": {"type": "string"},
                    "version": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 8},
                },
                "required": ["page", "pattern"],
                "additionalProperties": False,
            },
            traits=ToolTraits(read_only=True, concurrency_safe=True),
            semantics=_read_only_semantics(
                title="Find technical evidence",
                operation="technical_web_find",
                summary_prefix="Find technical evidence",
                subtitle_key="pattern",
                risk_level=ToolRiskLevel.READ,
            ),
            validate_input=validate_technical_web_find,
            execute=technical_web_find_tool,
            origin=origin,
        ),
    )


def _read_only_semantics(
    *,
    title: str,
    operation: str,
    summary_prefix: str,
    subtitle_key: str,
    risk_level: ToolRiskLevel,
):
    return static_semantics(
        read_only=True,
        concurrency_safe=True,
        tool_use_presentation=lambda tool_input, _context: ToolUsePresentation(
            title=title,
            subtitle=str(tool_input.get(subtitle_key) or "web research"),
            emphasis=ToolPresentationEmphasis.LOW,
        ),
        classifier_input=lambda tool_input, _context: ToolClassifierInput(
            operation=operation,
            summary=f"{summary_prefix}: {tool_input.get(subtitle_key) or 'web research'}",
            risk_level=risk_level,
            side_effects=False,
            tags=("coding", "web", "research"),
        ),
    )


def _network_semantics(
    *,
    title: str,
    operation: str,
    summary_prefix: str,
    subtitle_key: str,
):
    return static_semantics(
        read_only=True,
        concurrency_safe=True,
        tool_use_presentation=lambda tool_input, _context: ToolUsePresentation(
            title=title,
            subtitle=str(tool_input.get(subtitle_key) or tool_input.get("query") or "web research"),
            emphasis=ToolPresentationEmphasis.LOW,
        ),
        classifier_input=lambda tool_input, _context: ToolClassifierInput(
            operation=operation,
            summary=f"{summary_prefix}: {tool_input.get(subtitle_key) or tool_input.get('query') or 'web research'}",
            target_urls=(
                (str(tool_input["url"]),)
                if subtitle_key == "url" and tool_input.get("url") is not None
                else ()
            ),
            risk_level=ToolRiskLevel.NETWORK,
            side_effects=False,
            tags=("coding", "web", "research"),
        ),
    )
