from __future__ import annotations

from weavert.builtins.definition_helpers import file_semantics, static_semantics
from weavert.builtins.tool_impls import ask_permission
from weavert.definitions import (
    AgentDefinition,
    DefinitionOrigin,
    DefinitionSource,
    ToolCallStatus,
    ToolClassifierInput,
    ToolDefinition,
    ToolFailureClassifier,
    ToolFailureMode,
    ToolFailurePolicy,
    ToolPresentationEmphasis,
    ToolRiskLevel,
    ToolTraits,
    ToolUsePresentation,
)
from .tool_impls import (
    bash_tool,
    edit_file_tool,
    glob_tool,
    grep_tool,
    read_file_tool,
    validate_bash_tool,
    validate_edit_tool,
    validate_read_tool,
    validate_url_tool,
    validate_web_search,
    validate_write_tool,
    web_fetch_tool,
    web_search_tool,
    write_file_tool,
)


def devtools_builtin_tools() -> tuple[ToolDefinition, ...]:
    origin = DefinitionOrigin(DefinitionSource.BUNDLED)
    return (
        ToolDefinition(
            name="read",
            aliases=("Read",),
            description="Read files from the workspace without modifying them.",
            search_hint="read files",
            input_schema={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                    "offset": {"type": "integer", "minimum": 0},
                    "limit": {"type": "integer", "minimum": 1},
                },
                "required": ["file_path"],
                "additionalProperties": False,
            },
            traits=ToolTraits(read_only=True, concurrency_safe=True),
            semantics=file_semantics(
                operation="read_file",
                read_only=True,
                concurrency_safe=True,
                summary="Read file",
                risk_level=ToolRiskLevel.READ,
            ),
            validate_input=validate_read_tool,
            execute=read_file_tool,
            origin=origin,
        ),
        ToolDefinition(
            name="glob",
            aliases=("Glob",),
            description="Match filesystem paths using glob patterns.",
            search_hint="search file paths",
            input_schema={
                "type": "object",
                "properties": {
                    "pattern": {"type": "string"},
                    "root": {"type": "string"},
                },
                "required": ["pattern"],
                "additionalProperties": False,
            },
            traits=ToolTraits(read_only=True, concurrency_safe=True),
            semantics=static_semantics(
                read_only=True,
                concurrency_safe=True,
                tool_use_presentation=lambda tool_input, _context: ToolUsePresentation(
                    title="Match paths",
                    subtitle=tool_input.get("pattern"),
                    emphasis=ToolPresentationEmphasis.LOW,
                ),
                classifier_input=lambda tool_input, _context: ToolClassifierInput(
                    operation="glob",
                    summary=f"Match paths: {tool_input['pattern']}",
                    risk_level=ToolRiskLevel.READ,
                    side_effects=False,
                    tags=("filesystem", "glob"),
                ),
            ),
            execute=glob_tool,
            origin=origin,
        ),
        ToolDefinition(
            name="grep",
            aliases=("Grep",),
            description="Search file contents using regular expressions.",
            search_hint="search file contents",
            input_schema={
                "type": "object",
                "properties": {
                    "pattern": {"type": "string"},
                    "path": {"type": "string"},
                    "case_sensitive": {"type": "boolean"},
                },
                "required": ["pattern"],
                "additionalProperties": False,
            },
            traits=ToolTraits(read_only=True, concurrency_safe=True),
            semantics=static_semantics(
                read_only=True,
                concurrency_safe=True,
                tool_use_presentation=lambda tool_input, _context: ToolUsePresentation(
                    title="Search files",
                    subtitle=tool_input.get("pattern"),
                    emphasis=ToolPresentationEmphasis.LOW,
                ),
                classifier_input=lambda tool_input, _context: ToolClassifierInput(
                    operation="grep",
                    summary=f"Search files: {tool_input['pattern']}",
                    target_paths=(
                        (str(tool_input["path"]),) if tool_input.get("path") is not None else ()
                    ),
                    risk_level=ToolRiskLevel.READ,
                    side_effects=False,
                    tags=("filesystem", "search"),
                ),
            ),
            execute=grep_tool,
            origin=origin,
        ),
        ToolDefinition(
            name="edit",
            aliases=("Edit",),
            description="Apply targeted edits to an existing file.",
            input_schema={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                    "old_string": {"type": "string"},
                    "new_string": {"type": "string"},
                    "replace_all": {"type": "boolean"},
                },
                "required": ["file_path", "old_string", "new_string"],
                "additionalProperties": False,
            },
            semantics=file_semantics(
                operation="edit_file",
                read_only=False,
                concurrency_safe=False,
                summary="Edit file",
                risk_level=ToolRiskLevel.WRITE,
                failure_policy=ToolFailurePolicy(
                    failure_mode=ToolFailureMode.ERROR_RESULT,
                    result_classifier=ToolFailureClassifier.EXCEPTION_ONLY,
                    surfaced_status=ToolCallStatus.ERROR,
                ),
            ),
            validate_input=validate_edit_tool,
            check_permissions=ask_permission,
            execute=edit_file_tool,
            origin=origin,
        ),
        ToolDefinition(
            name="write",
            aliases=("Write",),
            description="Write a full file payload to disk.",
            input_schema={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["file_path", "content"],
                "additionalProperties": False,
            },
            traits=ToolTraits(destructive=True),
            semantics=file_semantics(
                operation="write_file",
                read_only=False,
                concurrency_safe=False,
                summary="Write file",
                risk_level=ToolRiskLevel.WRITE,
                failure_policy=ToolFailurePolicy(
                    failure_mode=ToolFailureMode.ERROR_RESULT,
                    result_classifier=ToolFailureClassifier.EXCEPTION_ONLY,
                    surfaced_status=ToolCallStatus.ERROR,
                ),
            ),
            validate_input=validate_write_tool,
            check_permissions=ask_permission,
            execute=write_file_tool,
            origin=origin,
        ),
        ToolDefinition(
            name="bash",
            aliases=("Bash",),
            description="Run a shell command in the current environment.",
            input_schema={
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "cwd": {"type": "string"},
                    "shell": {"type": "string", "enum": ["bash", "powershell"]},
                    "timeout_ms": {"type": "integer", "minimum": 1},
                },
                "required": ["command"],
                "additionalProperties": False,
            },
            semantics=static_semantics(
                read_only=False,
                concurrency_safe=False,
                failure_policy=ToolFailurePolicy(
                    failure_mode=ToolFailureMode.FATAL,
                    result_classifier=ToolFailureClassifier.NONZERO_EXIT_OR_EXCEPTION,
                    cancel_running_siblings=True,
                    block_queued_siblings=True,
                    abort_model_stream=True,
                    surfaced_status=ToolCallStatus.ERROR,
                ),
                tool_use_presentation=lambda tool_input, _context: ToolUsePresentation(
                    title="Run shell command",
                    subtitle=tool_input.get("command"),
                    emphasis=ToolPresentationEmphasis.HIGH,
                ),
                classifier_input=lambda tool_input, _context: ToolClassifierInput(
                    operation="bash",
                    summary=f"Execute shell command: {tool_input['command']}",
                    target_paths=(
                        (str(tool_input["cwd"]),) if tool_input.get("cwd") is not None else ()
                    ),
                    risk_level=ToolRiskLevel.EXEC,
                    side_effects=True,
                    tags=("shell", "exec"),
                ),
            ),
            validate_input=validate_bash_tool,
            check_permissions=ask_permission,
            execute=bash_tool,
            origin=origin,
        ),
        ToolDefinition(
            name="web_fetch",
            aliases=("WebFetch",),
            description="Fetch a single remote resource and return a compatibility payload plus additive source metadata.",
            input_schema={
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "domains": {"type": "array", "items": {"type": "string"}},
                    "freshness_days": {"type": "integer", "minimum": 0},
                    "timeout_ms": {"type": "integer", "minimum": 1},
                },
                "required": ["url"],
                "additionalProperties": False,
            },
            traits=ToolTraits(read_only=True, concurrency_safe=True),
            semantics=static_semantics(
                read_only=True,
                concurrency_safe=True,
                tool_use_presentation=lambda tool_input, _context: ToolUsePresentation(
                    title="Fetch URL",
                    subtitle=tool_input.get("url"),
                    emphasis=ToolPresentationEmphasis.LOW,
                ),
                classifier_input=lambda tool_input, _context: ToolClassifierInput(
                    operation="web_fetch",
                    summary=f"Fetch URL: {tool_input['url']}",
                    target_urls=(str(tool_input["url"]),),
                    risk_level=ToolRiskLevel.NETWORK,
                    side_effects=False,
                    tags=("network", "fetch"),
                ),
            ),
            validate_input=validate_url_tool,
            execute=web_fetch_tool,
            origin=origin,
        ),
        ToolDefinition(
            name="web_search",
            aliases=("WebSearch",),
            description="Search the web for recent information while preserving the legacy `query` and `results` fields.",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "domains": {"type": "array", "items": {"type": "string"}},
                    "freshness_days": {"type": "integer", "minimum": 0},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 10},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
            traits=ToolTraits(read_only=True, concurrency_safe=True),
            semantics=static_semantics(
                read_only=True,
                concurrency_safe=True,
                tool_use_presentation=lambda tool_input, _context: ToolUsePresentation(
                    title="Search web",
                    subtitle=tool_input.get("query"),
                    emphasis=ToolPresentationEmphasis.LOW,
                ),
                classifier_input=lambda tool_input, _context: ToolClassifierInput(
                    operation="web_search",
                    summary=f"Search web: {tool_input['query']}",
                    risk_level=ToolRiskLevel.NETWORK,
                    side_effects=False,
                    tags=("network", "search"),
                ),
            ),
            validate_input=validate_web_search,
            execute=web_search_tool,
            origin=origin,
        ),
    )


def devtools_builtin_agents() -> tuple[AgentDefinition, ...]:
    origin = DefinitionOrigin(DefinitionSource.BUNDLED)
    return (
        AgentDefinition(
            name="explore",
            description="Investigate the codebase and summarize findings.",
            prompt="You are an exploration agent focused on gathering accurate context.",
            tools=("read", "glob", "grep", "web_fetch", "web_search"),
            origin=origin,
        ),
        AgentDefinition(
            name="plan",
            description="Break a larger task into defensible execution steps.",
            prompt="You are a planning agent. Produce concrete, ordered next steps.",
            tools=("read", "glob", "grep"),
            origin=origin,
        ),
        AgentDefinition(
            name="verification",
            description="Run tests, validations, and quality checks.",
            prompt="You are a verification agent. Focus on tests and regressions.",
            tools=("read", "glob", "grep", "bash"),
            origin=origin,
        ),
    )


__all__ = [
    "devtools_builtin_agents",
    "devtools_builtin_tools",
]
