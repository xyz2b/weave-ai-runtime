from __future__ import annotations

from weavert.builtins.definition_helpers import static_semantics
from weavert.definitions import (
    AgentDefinition,
    DefinitionOrigin,
    DefinitionSource,
    MemoryScope,
    PermissionMode,
    SkillDefinition,
    SkillExecutionContext,
    ToolClassifierInput,
    ToolDefinition,
    ToolPresentationEmphasis,
    ToolRiskLevel,
    ToolTraits,
    ToolUsePresentation,
)
from ._tool_impls import (
    grounding_web_fetch_tool,
    grounding_web_find_tool,
    grounding_web_search_tool,
    prepare_citations_tool,
    retrieve_context_tool,
    validate_grounding_web_fetch,
    validate_grounding_web_find,
    validate_grounding_web_search,
    validate_prepare_citations_tool,
    validate_retrieve_context_tool,
    validate_web_research,
    validate_web_research_fetch_many,
    web_research_fetch_many_tool,
    web_research_tool,
)

CHAT_RETRIEVAL_TOOLS = (
    "retrieve_context",
    "prepare_citations",
)
CHAT_WEB_TOOLS = (
    "web_research",
    "grounding_web_search",
    "grounding_web_fetch",
    "grounding_web_find",
    "web_research_fetch_many",
)
WEB_RESEARCH_WORKER_AGENTS = ("web-searcher",)
CHAT_SCENARIO_AGENTS = (
    "researcher",
    "support-agent",
    "memory-curator",
)
CHAT_SCENARIO_SKILLS = (
    "chat-summarize",
    "answer-with-citations",
    "clarify-request",
    "capture-preferences",
)


def chat_shared_retrieval_builtin_tools() -> tuple[ToolDefinition, ...]:
    origin = DefinitionOrigin(DefinitionSource.BUNDLED)
    item_schema = {
        "type": "object",
        "properties": {
            "id": {"type": "string"},
            "title": {"type": "string"},
            "content": {"type": "string"},
            "excerpt": {"type": "string"},
            "url": {"type": "string"},
            "source_kind": {"type": "string"},
            "metadata": {"type": "object"},
        },
        "additionalProperties": True,
    }
    return (
        ToolDefinition(
            name="retrieve_context",
            description="Rank grounding notes, passages, and optional runtime memory for a chat query.",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "items": {"type": "array", "items": item_schema},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 12},
                    "include_memory": {"type": "boolean"},
                    "memory_scope": {
                        "type": "string",
                        "enum": [MemoryScope.USER.value, MemoryScope.PROJECT.value, MemoryScope.LOCAL.value],
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
            traits=ToolTraits(read_only=True, concurrency_safe=True),
            semantics=_read_only_tool_semantics(
                title="Retrieve grounding context",
                operation="retrieve_context",
                summary_prefix="Retrieve grounding context",
                subtitle_key="query",
                risk_level=ToolRiskLevel.READ,
                tags=("grounding", "retrieval"),
            ),
            validate_input=validate_retrieve_context_tool,
            execute=retrieve_context_tool,
            origin=origin,
        ),
        ToolDefinition(
            name="prepare_citations",
            description="Turn retrieved grounding items into a flat citation bundle for chat answers.",
            input_schema={
                "type": "object",
                "properties": {
                    "items": {"type": "array", "items": item_schema},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 12},
                },
                "required": ["items"],
                "additionalProperties": False,
            },
            traits=ToolTraits(read_only=True, concurrency_safe=True),
            semantics=_read_only_tool_semantics(
                title="Prepare citations",
                operation="prepare_citations",
                summary_prefix="Prepare citations",
                subtitle_key="limit",
                risk_level=ToolRiskLevel.READ,
                tags=("grounding", "citations"),
            ),
            validate_input=validate_prepare_citations_tool,
            execute=prepare_citations_tool,
            origin=origin,
        ),
    )


def chat_web_grounding_builtin_tools() -> tuple[ToolDefinition, ...]:
    origin = DefinitionOrigin(DefinitionSource.BUNDLED)
    return (
        ToolDefinition(
            name="web_research",
            description="Run bounded AI-first read-only web research through the package-owned delegated web-searcher agent.",
            input_schema={
                "type": "object",
                "properties": {
                    "objective": {"type": "string"},
                    "question": {"type": "string"},
                    "mode": {"type": "string", "enum": ["focused", "open"]},
                    "domains": {"type": "array", "items": {"type": "string"}},
                    "allowed_domains": {"type": "array", "items": {"type": "string"}},
                    "blocked_domains": {"type": "array", "items": {"type": "string"}},
                    "hard_policy": {"type": "object"},
                    "preferences": {"type": "object"},
                    "budget_profile": {"type": "string", "enum": ["quick", "standard", "deep"]},
                    "freshness_days": {"type": "integer", "minimum": 0},
                    "recency_days": {"type": "integer", "minimum": 0},
                    "search_budget": {"type": "integer", "minimum": 1, "maximum": 8},
                    "fetch_budget": {"type": "integer", "minimum": 0, "maximum": 8},
                    "find_budget": {"type": "integer", "minimum": 0, "maximum": 12},
                    "desired_source_count": {"type": "integer", "minimum": 1, "maximum": 8},
                    "max_turns": {"type": "integer", "minimum": 1, "maximum": 8},
                    "max_concurrent_fetches": {"type": "integer", "minimum": 1, "maximum": 5},
                    "max_chars": {"type": "integer", "minimum": 500, "maximum": 32000},
                    "output_hints": {"type": "object"},
                },
                "additionalProperties": False,
            },
            output_schema={
                "type": "object",
                "properties": {
                    "objective": {"type": "string"},
                    "mode": {"type": "string"},
                    "answer": {"type": "string"},
                    "sources": {"type": "array", "items": {"type": "object"}},
                    "evidence": {"type": "array", "items": {"type": "object"}},
                    "policy": {"type": "object"},
                    "hard_policy": {"type": "object"},
                    "preferences": {"type": "object"},
                    "budget": {"type": "object"},
                    "stop_reason": {"type": "string"},
                    "trace_summary": {"type": "array", "items": {"type": "object"}},
                    "child_run": {"type": "object"},
                },
                "required": [
                    "objective",
                    "mode",
                    "answer",
                    "sources",
                    "evidence",
                    "policy",
                    "hard_policy",
                    "preferences",
                    "budget",
                    "stop_reason",
                    "trace_summary",
                    "child_run",
                ],
                "additionalProperties": False,
            },
            traits=ToolTraits(read_only=True, concurrency_safe=False),
            semantics=_network_tool_semantics(
                title="Research web evidence",
                operation="web_research",
                summary_prefix="Research web evidence",
                subtitle_key="objective",
                tags=("grounding", "web", "research"),
            ),
            validate_input=validate_web_research,
            execute=web_research_tool,
            runtime_execution_class="privileged",
            origin=origin,
        ),
        ToolDefinition(
            name="grounding_web_search",
            description="Search the public web for chat-safe grounding candidates with explicit source handles.",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "domains": {"type": "array", "items": {"type": "string"}},
                    "freshness_days": {"type": "integer", "minimum": 0},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 8},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
            traits=ToolTraits(read_only=True, concurrency_safe=True),
            semantics=_network_tool_semantics(
                title="Search grounding sources",
                operation="grounding_web_search",
                summary_prefix="Search grounding sources",
                subtitle_key="query",
                tags=("grounding", "web", "search"),
            ),
            validate_input=validate_grounding_web_search,
            execute=grounding_web_search_tool,
            origin=origin,
        ),
        ToolDefinition(
            name="grounding_web_fetch",
            description="Inspect a remote page and return chat-safe text plus citation-ready source metadata.",
            input_schema={
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "source": {
                        "type": "object",
                        "properties": {
                            "url": {"type": "string"},
                            "title": {"type": "string"},
                            "source_handle": {"type": "string"},
                            "page_handle": {"type": "string"},
                        },
                        "additionalProperties": True,
                    },
                    "domains": {"type": "array", "items": {"type": "string"}},
                    "freshness_days": {"type": "integer", "minimum": 0},
                    "timeout_ms": {"type": "integer", "minimum": 1},
                    "max_chars": {"type": "integer", "minimum": 500, "maximum": 32000},
                },
                "additionalProperties": False,
            },
            traits=ToolTraits(read_only=True, concurrency_safe=True),
            semantics=_network_tool_semantics(
                title="Fetch grounding page",
                operation="grounding_web_fetch",
                summary_prefix="Fetch grounding page",
                subtitle_key="url",
                tags=("grounding", "web", "fetch"),
            ),
            validate_input=validate_grounding_web_fetch,
            execute=grounding_web_fetch_tool,
            origin=origin,
        ),
        ToolDefinition(
            name="grounding_web_find",
            description="Find local evidence inside an inspected grounding page without re-fetching it.",
            input_schema={
                "type": "object",
                "properties": {
                    "page": {
                        "type": "object",
                        "properties": {
                            "url": {"type": "string"},
                            "title": {"type": "string"},
                            "content": {"type": "string"},
                            "source_handle": {"type": "string"},
                            "page_handle": {"type": "string"},
                        },
                        "additionalProperties": True,
                    },
                    "pattern": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 8},
                },
                "required": ["page", "pattern"],
                "additionalProperties": False,
            },
            traits=ToolTraits(read_only=True, concurrency_safe=True),
            semantics=_read_only_tool_semantics(
                title="Find grounding evidence",
                operation="grounding_web_find",
                summary_prefix="Find grounding evidence",
                subtitle_key="pattern",
                risk_level=ToolRiskLevel.READ,
                tags=("grounding", "web", "find"),
            ),
            validate_input=validate_grounding_web_find,
            execute=grounding_web_find_tool,
            origin=origin,
        ),
        ToolDefinition(
            name="web_research_fetch_many",
            description="Inspect multiple web research candidate URLs concurrently inside the active web_research policy and budget.",
            input_schema={
                "type": "object",
                "properties": {
                    "urls": {"type": "array", "items": {"type": "string"}},
                    "sources": {"type": "array", "items": {"type": "object"}},
                    "max_concurrent_fetches": {"type": "integer", "minimum": 1, "maximum": 5},
                    "timeout_ms": {"type": "integer", "minimum": 1},
                    "max_chars": {"type": "integer", "minimum": 500, "maximum": 32000},
                },
                "additionalProperties": False,
            },
            traits=ToolTraits(read_only=True, concurrency_safe=False),
            semantics=_network_tool_semantics(
                title="Fetch research pages",
                operation="web_research_fetch_many",
                summary_prefix="Fetch research pages",
                subtitle_key="max_concurrent_fetches",
                tags=("grounding", "web", "research", "fetch"),
            ),
            validate_input=validate_web_research_fetch_many,
            execute=web_research_fetch_many_tool,
            origin=origin,
        ),
    )


def chat_scenario_builtin_agents() -> tuple[AgentDefinition, ...]:
    origin = DefinitionOrigin(DefinitionSource.BUNDLED)
    return (
        AgentDefinition(
            name="researcher",
            description="Gather read-only evidence bundles for grounded chat answers.",
            prompt=(
                "You are the grounded-chat researcher.\n\n"
                "Workflow contract:\n"
                "1. Start with read-only grounding surfaces.\n"
                "2. Prefer `web_research` for fresh external facts that need bounded source discovery and inspection.\n"
                "3. Use `grounding_web_search`, `grounding_web_fetch`, and `grounding_web_find` only when explicit low-level orchestration is needed.\n"
                "4. Use `retrieve_context` to rank notes, memory, or inspected passages before summarizing.\n"
                "5. Use `prepare_citations` before handing off a final evidence bundle.\n"
                "6. Never imply shell access, workspace mutation, or uninspected sources."
            ),
            tools=(*CHAT_RETRIEVAL_TOOLS, *CHAT_WEB_TOOLS, "ask_user"),
            skills=("chat-summarize", "answer-with-citations", "clarify-request"),
            permission_mode=PermissionMode.DEFAULT,
            max_turns=6,
            memory=MemoryScope.PROJECT,
            origin=origin,
        ),
        AgentDefinition(
            name="support-agent",
            description="Answer user support questions with clarification and citations.",
            prompt=(
                "You are the grounded-chat support agent.\n\n"
                "Workflow contract:\n"
                "1. Clarify the user's goal when the policy, product, or account scope is ambiguous.\n"
                "2. Prefer cited, read-only answers over unsupported guesses.\n"
                "3. Prefer `web_research` plus retrieval before finalizing an answer; use low-level web primitives for explicit source inspection flows.\n"
                "4. Capture durable user preferences only when they are explicit and stable.\n"
                "5. Do not request workspace or shell mutation as part of the default support flow."
            ),
            tools=(*CHAT_RETRIEVAL_TOOLS, *CHAT_WEB_TOOLS, "ask_user"),
            skills=(
                "chat-summarize",
                "answer-with-citations",
                "clarify-request",
                "capture-preferences",
                "remember",
            ),
            permission_mode=PermissionMode.DEFAULT,
            max_turns=6,
            memory=MemoryScope.PROJECT,
            origin=origin,
        ),
        AgentDefinition(
            name="memory-curator",
            description="Curate durable chat preferences and reusable support facts.",
            prompt=(
                "You are the grounded-chat memory curator.\n\n"
                "Workflow contract:\n"
                "1. Inspect recent context and retrieved notes before recording anything durable.\n"
                "2. Prefer stable preferences, conventions, and reusable support facts.\n"
                "3. Use `remember` only when the information is explicit, durable, and helpful later.\n"
                "4. Keep the posture read-mostly and never ask for coding-oriented mutation surfaces."
            ),
            tools=(*CHAT_RETRIEVAL_TOOLS, "ask_user"),
            skills=("capture-preferences", "remember", "chat-summarize"),
            permission_mode=PermissionMode.DEFAULT,
            max_turns=4,
            memory=MemoryScope.PROJECT,
            origin=origin,
        ),
    )


def web_research_worker_builtin_agents() -> tuple[AgentDefinition, ...]:
    origin = DefinitionOrigin(DefinitionSource.BUNDLED)
    return (
        AgentDefinition(
            name="web-searcher",
            description="Package-owned delegated worker for bounded read-only web_research execution.",
            prompt=(
                "You are the common-web package delegated web research worker.\n\n"
                "Workflow contract:\n"
                "1. Serve only `web_research` child runs or package extension paths.\n"
                "2. Use the controlled read-only tool pool: `grounding_web_search`, "
                "`grounding_web_fetch`, `grounding_web_find`, and `web_research_fetch_many`.\n"
                "3. Stay inside caller-provided hard policy and budgets; open-mode preferences guide ranking, not safety.\n"
                "4. Inspect evidence before citing it, and return source references plus concise evidence.\n"
                "5. Use `web_research_fetch_many` only for bounded concurrent page inspection.\n"
                "6. Do not request shell access, workspace mutation, browser navigation, or direct user adoption."
            ),
            tools=("grounding_web_search", "grounding_web_fetch", "grounding_web_find", "web_research_fetch_many"),
            permission_mode=PermissionMode.DEFAULT,
            max_turns=4,
            origin=origin,
        ),
    )


def chat_scenario_builtin_skills() -> tuple[SkillDefinition, ...]:
    origin = DefinitionOrigin(DefinitionSource.BUNDLED)
    return (
        SkillDefinition(
            name="chat-summarize",
            description="Summarize retrieved grounding without dropping important caveats.",
            content=(
                "Summarize the material already in hand.\n\n"
                "1. Start from retrieved notes, fetched passages, or durable memory.\n"
                "2. Separate confirmed facts from uncertainty.\n"
                "3. Keep the summary concise, user-facing, and faithful to the sources."
            ),
            execution_context=SkillExecutionContext.INLINE,
            origin=origin,
        ),
        SkillDefinition(
            name="answer-with-citations",
            description="Assemble a grounded answer that cites supporting evidence explicitly.",
            content=(
                "Answer with visible grounding.\n\n"
                "1. Retrieve or fetch the best evidence first.\n"
                "2. Call `prepare_citations` on the supporting items before drafting the answer.\n"
                "3. Cite only evidence you actually inspected.\n"
                "4. State uncertainty when the grounding is thin or incomplete."
            ),
            execution_context=SkillExecutionContext.INLINE,
            origin=origin,
        ),
        SkillDefinition(
            name="clarify-request",
            description="Ask a short clarification before grounding an ambiguous request.",
            content=(
                "When the request is ambiguous or missing the policy/product scope:\n\n"
                "1. Ask the shortest question that unblocks a grounded answer.\n"
                "2. Prefer one focused clarification over a long questionnaire.\n"
                "3. Resume grounding once the missing detail is provided."
            ),
            execution_context=SkillExecutionContext.INLINE,
            origin=origin,
        ),
        SkillDefinition(
            name="capture-preferences",
            description="Record durable user preferences and recurring support facts.",
            content=(
                "Capture only stable preferences or reusable support facts.\n\n"
                "1. Confirm the preference or fact is explicit and durable.\n"
                "2. Use `remember` when the information should survive future turns.\n"
                "3. Skip volatile or one-off details."
            ),
            execution_context=SkillExecutionContext.INLINE,
            origin=origin,
        ),
    )


def _read_only_tool_semantics(
    *,
    title: str,
    operation: str,
    summary_prefix: str,
    subtitle_key: str,
    risk_level: ToolRiskLevel,
    tags: tuple[str, ...],
):
    return static_semantics(
        read_only=True,
        concurrency_safe=True,
        tool_use_presentation=lambda tool_input, _context: ToolUsePresentation(
            title=title,
            subtitle=str(tool_input.get(subtitle_key) or "grounding"),
            emphasis=ToolPresentationEmphasis.LOW,
        ),
        classifier_input=lambda tool_input, _context: ToolClassifierInput(
            operation=operation,
            summary=f"{summary_prefix}: {tool_input.get(subtitle_key) or 'grounding'}",
            risk_level=risk_level,
            side_effects=False,
            tags=tags,
        ),
    )


def _network_tool_semantics(
    *,
    title: str,
    operation: str,
    summary_prefix: str,
    subtitle_key: str,
    tags: tuple[str, ...],
):
    return static_semantics(
        read_only=True,
        concurrency_safe=True,
        tool_use_presentation=lambda tool_input, _context: ToolUsePresentation(
            title=title,
            subtitle=str(tool_input.get(subtitle_key) or "grounding"),
            emphasis=ToolPresentationEmphasis.LOW,
        ),
        classifier_input=lambda tool_input, _context: ToolClassifierInput(
            operation=operation,
            summary=f"{summary_prefix}: {tool_input.get(subtitle_key) or 'grounding'}",
            target_urls=(
                (str(tool_input[subtitle_key]),)
                if subtitle_key == "url" and tool_input.get(subtitle_key) is not None
                else ()
            ),
            risk_level=ToolRiskLevel.NETWORK,
            side_effects=False,
            tags=tags,
        ),
    )


__all__ = [
    "CHAT_RETRIEVAL_TOOLS",
    "CHAT_SCENARIO_AGENTS",
    "CHAT_SCENARIO_SKILLS",
    "CHAT_WEB_TOOLS",
    "WEB_RESEARCH_WORKER_AGENTS",
    "chat_scenario_builtin_agents",
    "chat_scenario_builtin_skills",
    "chat_shared_retrieval_builtin_tools",
    "chat_web_grounding_builtin_tools",
    "web_research_worker_builtin_agents",
]
