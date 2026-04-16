from __future__ import annotations

from typing import Any

from ..definitions import (
    DefinitionOrigin,
    DefinitionSource,
    InterruptBehavior,
    ToolCallStatus,
    ToolClassifierInput,
    ToolDefinition,
    ToolExecutionSemantics,
    ToolFailureClassifier,
    ToolFailureMode,
    ToolFailurePolicy,
    ToolPresentationEmphasis,
    ToolResultSummary,
    ToolResultSummaryStatus,
    ToolRiskLevel,
    ToolTraits,
    ToolUsePresentation,
)
from .tool_impls import (
    agent_tool,
    ask_permission,
    ask_user_tool,
    bash_tool,
    edit_file_tool,
    glob_tool,
    grep_tool,
    read_file_tool,
    skill_tool,
    sleep_tool,
    task_create_tool,
    task_get_tool,
    task_list_tool,
    task_stop_tool,
    task_update_tool,
    validate_agent_tool,
    validate_bash_tool,
    validate_edit_tool,
    validate_read_tool,
    validate_skill_registry_entry,
    validate_sleep_tool,
    validate_url_tool,
    validate_web_search,
    validate_write_tool,
    web_fetch_tool,
    web_search_tool,
    write_file_tool,
)


def _static_semantics(
    *,
    read_only: bool = False,
    concurrency_safe: bool = False,
    interrupt_behavior: InterruptBehavior = InterruptBehavior.BLOCK,
    failure_policy: ToolFailurePolicy | None = None,
    tool_use_presentation=None,
    tool_result_summary=None,
    classifier_input=None,
) -> ToolExecutionSemantics:
    return ToolExecutionSemantics(
        is_read_only=lambda _tool_input, _context: read_only,
        is_concurrency_safe=lambda _tool_input, _context: concurrency_safe,
        interrupt_behavior=lambda _tool_input, _context: interrupt_behavior,
        failure_policy=lambda _tool_input, _context: failure_policy or ToolFailurePolicy(),
        render_tool_use_message=tool_use_presentation or (lambda _tool_input, _context: None),
        render_tool_result_summary=tool_result_summary or (lambda _tool_input, _context: None),
        to_classifier_input=classifier_input or (lambda _tool_input, _context: None),
    )


def _file_semantics(
    *,
    operation: str,
    read_only: bool,
    concurrency_safe: bool,
    summary: str,
    risk_level: ToolRiskLevel,
    failure_policy: ToolFailurePolicy | None = None,
) -> ToolExecutionSemantics:
    return _static_semantics(
        read_only=read_only,
        concurrency_safe=concurrency_safe,
        failure_policy=failure_policy,
        tool_use_presentation=lambda tool_input, _context: ToolUsePresentation(
            title=summary,
            subtitle=tool_input.get("file_path"),
            emphasis=(
                ToolPresentationEmphasis.LOW
                if read_only
                else ToolPresentationEmphasis.NORMAL
            ),
        ),
        tool_result_summary=lambda tool_input, _context: ToolResultSummary(
            title=summary,
            summary=tool_input.get("file_path", summary),
            status=(
                ToolResultSummaryStatus.SUCCESS
                if read_only
                else ToolResultSummaryStatus.SUCCESS
            ),
        ),
        classifier_input=lambda tool_input, _context: ToolClassifierInput(
            operation=operation,
            summary=f"{summary}: {tool_input.get('file_path', '')}".strip(": "),
            target_paths=(
                (str(tool_input["file_path"]),)
                if tool_input.get("file_path") is not None
                else ()
            ),
            risk_level=risk_level,
            side_effects=not read_only,
            tags=("filesystem", operation),
        ),
    )


def builtin_tools() -> tuple[ToolDefinition, ...]:
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
            semantics=_file_semantics(
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
            semantics=_static_semantics(
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
            semantics=_static_semantics(
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
            semantics=_file_semantics(
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
            semantics=_file_semantics(
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
                    "timeout_ms": {"type": "integer", "minimum": 1},
                },
                "required": ["command"],
                "additionalProperties": False,
            },
            semantics=_static_semantics(
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
            description="Fetch a single remote resource and return its content.",
            input_schema={
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "timeout_ms": {"type": "integer", "minimum": 1},
                },
                "required": ["url"],
                "additionalProperties": False,
            },
            traits=ToolTraits(read_only=True, concurrency_safe=True),
            semantics=_static_semantics(
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
            description="Search the web for recent information.",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 10},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
            traits=ToolTraits(read_only=True, concurrency_safe=True),
            semantics=_static_semantics(
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
        ToolDefinition(
            name="agent",
            aliases=("Agent",),
            description="Spawn or communicate with a subagent.",
            input_schema={
                "type": "object",
                "properties": {
                    "agent": {"type": "string"},
                    "prompt": {"type": "string"},
                    "background": {"type": "boolean"},
                    "spawn_mode": {
                        "type": "string",
                        "enum": ["sync", "background"],
                    },
                    "cwd": {"type": "string"},
                    "model": {"type": "string"},
                    "model_route": {"type": "string"},
                    "reason": {"type": "string"},
                    "permission_mode": {
                        "type": "string",
                        "enum": [
                            "default",
                            "plan",
                            "acceptEdits",
                            "bypassPermissions",
                            "dontAsk",
                            "auto",
                            "bubble",
                        ],
                    },
                    "isolation": {
                        "type": "string",
                        "enum": ["none", "worktree", "remote"],
                    },
                    "max_turns": {"type": "integer", "minimum": 1},
                },
                "required": ["agent", "prompt"],
                "additionalProperties": False,
            },
            output_schema={
                "type": "object",
                "properties": {
                    "agent": {"type": "string"},
                    "status": {"type": "string"},
                    "background": {"type": "boolean"},
                    "run_id": {"type": ["string", "null"]},
                    "parent_run_id": {"type": ["string", "null"]},
                    "turn_id": {"type": ["string", "null"]},
                    "query_source": {"type": ["string", "null"]},
                    "messages": {"type": "array"},
                    "task_id": {"type": ["string", "null"]},
                    "requested_model": {"type": ["string", "null"]},
                    "requested_model_route": {"type": ["string", "null"]},
                    "resolved_model_route": {"type": ["string", "null"]},
                    "isolation_mode": {"type": ["string", "null"]},
                    "terminal_metadata": {"type": "object"},
                    "notification": {"type": ["object", "null"]},
                },
                "required": [
                    "agent",
                    "status",
                    "background",
                    "run_id",
                    "parent_run_id",
                    "turn_id",
                    "query_source",
                    "messages",
                    "requested_model",
                    "requested_model_route",
                    "resolved_model_route",
                    "terminal_metadata",
                ],
                "additionalProperties": True,
            },
            semantics=_static_semantics(
                read_only=False,
                concurrency_safe=False,
                tool_use_presentation=lambda tool_input, _context: ToolUsePresentation(
                    title="Run agent",
                    subtitle=tool_input.get("agent"),
                    emphasis=ToolPresentationEmphasis.NORMAL,
                ),
                classifier_input=lambda tool_input, _context: ToolClassifierInput(
                    operation="agent",
                    summary=f"Delegate to agent: {tool_input['agent']}",
                    risk_level=ToolRiskLevel.DELEGATE,
                    side_effects=True,
                    tags=("delegate", "agent"),
                ),
            ),
            validate_input=validate_agent_tool,
            execute=agent_tool,
            origin=origin,
        ),
        ToolDefinition(
            name="skill",
            aliases=("Skill",),
            description="Invoke a registered runtime skill.",
            input_schema={
                "type": "object",
                "properties": {
                    "skill": {"type": "string"},
                    "arguments": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": ["skill"],
                "additionalProperties": False,
            },
            semantics=_static_semantics(
                read_only=False,
                concurrency_safe=False,
                tool_use_presentation=lambda tool_input, _context: ToolUsePresentation(
                    title="Run skill",
                    subtitle=tool_input.get("skill"),
                    emphasis=ToolPresentationEmphasis.NORMAL,
                ),
                classifier_input=lambda tool_input, _context: ToolClassifierInput(
                    operation="skill",
                    summary=f"Run skill: {tool_input['skill']}",
                    risk_level=ToolRiskLevel.DELEGATE,
                    side_effects=True,
                    tags=("delegate", "skill"),
                ),
            ),
            validate_input=validate_skill_registry_entry,
            execute=skill_tool,
            origin=origin,
        ),
        ToolDefinition(
            name="task_create",
            description="Create a background task record.",
            input_schema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"},
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "metadata": {"type": "object"},
                },
                "required": ["task_id", "title"],
                "additionalProperties": False,
            },
            execute=task_create_tool,
            origin=origin,
        ),
        ToolDefinition(
            name="task_get",
            description="Inspect a task by identifier.",
            input_schema={
                "type": "object",
                "properties": {"task_id": {"type": "string"}},
                "required": ["task_id"],
                "additionalProperties": False,
            },
            traits=ToolTraits(read_only=True, concurrency_safe=True),
            semantics=_static_semantics(
                read_only=True,
                concurrency_safe=True,
                classifier_input=lambda tool_input, _context: ToolClassifierInput(
                    operation="task_get",
                    summary=f"Inspect task: {tool_input['task_id']}",
                    risk_level=ToolRiskLevel.READ,
                    side_effects=False,
                    tags=("task", "read"),
                ),
            ),
            execute=task_get_tool,
            origin=origin,
        ),
        ToolDefinition(
            name="task_update",
            description="Update a task state or metadata.",
            input_schema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"},
                    "status": {
                        "type": "string",
                        "enum": ["pending", "running", "completed", "failed", "stopped"],
                    },
                    "result": {},
                    "error": {"type": "string"},
                    "metadata": {"type": "object"},
                },
                "required": ["task_id"],
                "additionalProperties": False,
            },
            execute=task_update_tool,
            origin=origin,
        ),
        ToolDefinition(
            name="task_list",
            description="List tracked tasks for the current session.",
            input_schema={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
            traits=ToolTraits(read_only=True, concurrency_safe=True),
            semantics=_static_semantics(
                read_only=True,
                concurrency_safe=True,
                classifier_input=lambda _tool_input, _context: ToolClassifierInput(
                    operation="task_list",
                    summary="List tasks",
                    risk_level=ToolRiskLevel.READ,
                    side_effects=False,
                    tags=("task", "read"),
                ),
            ),
            execute=task_list_tool,
            origin=origin,
        ),
        ToolDefinition(
            name="task_stop",
            aliases=("TaskStop",),
            description="Stop a running task or background process.",
            input_schema={
                "type": "object",
                "properties": {"task_id": {"type": "string"}},
                "required": ["task_id"],
                "additionalProperties": False,
            },
            traits=ToolTraits(destructive=True),
            semantics=_static_semantics(
                read_only=False,
                concurrency_safe=False,
                failure_policy=ToolFailurePolicy(
                    failure_mode=ToolFailureMode.ERROR_RESULT,
                    result_classifier=ToolFailureClassifier.EXCEPTION_ONLY,
                    surfaced_status=ToolCallStatus.ERROR,
                ),
                classifier_input=lambda tool_input, _context: ToolClassifierInput(
                    operation="task_stop",
                    summary=f"Stop task: {tool_input['task_id']}",
                    risk_level=ToolRiskLevel.WRITE,
                    side_effects=True,
                    tags=("task", "write"),
                ),
            ),
            check_permissions=ask_permission,
            execute=task_stop_tool,
            origin=origin,
        ),
        ToolDefinition(
            name="ask_user",
            aliases=("AskUser",),
            description="Request explicit user input from the host.",
            input_schema={
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "options": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": ["question"],
                "additionalProperties": False,
            },
            execute=ask_user_tool,
            origin=origin,
        ),
        ToolDefinition(
            name="sleep",
            aliases=("Sleep",),
            description="Pause for a bounded duration without blocking forever.",
            input_schema={
                "type": "object",
                "properties": {"seconds": {"type": "number", "minimum": 0, "maximum": 300}},
                "required": ["seconds"],
                "additionalProperties": False,
            },
            traits=ToolTraits(interrupt_behavior=InterruptBehavior.CANCEL),
            semantics=_static_semantics(
                read_only=True,
                concurrency_safe=True,
                interrupt_behavior=InterruptBehavior.CANCEL,
                classifier_input=lambda tool_input, _context: ToolClassifierInput(
                    operation="sleep",
                    summary=f"Sleep for {tool_input['seconds']} seconds",
                    risk_level=ToolRiskLevel.READ,
                    side_effects=False,
                    tags=("timing",),
                ),
            ),
            validate_input=validate_sleep_tool,
            execute=sleep_tool,
            origin=origin,
        ),
    )
