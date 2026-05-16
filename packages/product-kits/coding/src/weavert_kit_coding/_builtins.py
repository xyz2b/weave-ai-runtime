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
    git_diff_tool,
    git_history_tool,
    git_status_tool,
    validate_git_path_tool,
    validate_workspace_outline_tool,
    validate_workspace_query_tool,
    validate_workspace_symbol_tool,
    validate_workspace_test_targets_tool,
    workspace_outline_tool,
    workspace_references_tool,
    workspace_symbols_tool,
    workspace_test_targets_tool,
)


def shared_git_builtin_tools() -> tuple[ToolDefinition, ...]:
    origin = DefinitionOrigin(DefinitionSource.BUNDLED)
    return (
        ToolDefinition(
            name="git_status",
            description="Inspect the current git status for the workspace or a target path.",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "include_untracked": {"type": "boolean"},
                },
                "additionalProperties": False,
            },
            traits=ToolTraits(read_only=True, concurrency_safe=True),
            semantics=_read_only_tool_semantics(
                title="Inspect git status",
                operation="git_status",
                summary_prefix="Inspect git status",
                subtitle_key="path",
                risk_level=ToolRiskLevel.READ,
                tags=("git", "status"),
            ),
            validate_input=validate_git_path_tool,
            execute=git_status_tool,
            origin=origin,
        ),
        ToolDefinition(
            name="git_diff",
            description="Inspect a git diff for the workspace or a focused path.",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "cached": {"type": "boolean"},
                    "base_ref": {"type": "string"},
                    "head_ref": {"type": "string"},
                    "context_lines": {"type": "integer", "minimum": 0, "maximum": 20},
                },
                "additionalProperties": False,
            },
            traits=ToolTraits(read_only=True, concurrency_safe=True),
            semantics=_read_only_tool_semantics(
                title="Inspect git diff",
                operation="git_diff",
                summary_prefix="Inspect git diff",
                subtitle_key="path",
                risk_level=ToolRiskLevel.READ,
                tags=("git", "diff"),
            ),
            validate_input=validate_git_path_tool,
            execute=git_diff_tool,
            origin=origin,
        ),
        ToolDefinition(
            name="git_history",
            description="Inspect recent git history for the workspace or a target path.",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "ref": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 50},
                },
                "additionalProperties": False,
            },
            traits=ToolTraits(read_only=True, concurrency_safe=True),
            semantics=_read_only_tool_semantics(
                title="Inspect git history",
                operation="git_history",
                summary_prefix="Inspect git history",
                subtitle_key="path",
                risk_level=ToolRiskLevel.READ,
                tags=("git", "history"),
            ),
            validate_input=validate_git_path_tool,
            execute=git_history_tool,
            origin=origin,
        ),
    )


def shared_workspace_intelligence_builtin_tools() -> tuple[ToolDefinition, ...]:
    origin = DefinitionOrigin(DefinitionSource.BUNDLED)
    return (
        ToolDefinition(
            name="workspace_symbols",
            description="Locate likely symbol definitions across the workspace.",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "path": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
            traits=ToolTraits(read_only=True, concurrency_safe=True),
            semantics=_read_only_tool_semantics(
                title="Find workspace symbols",
                operation="workspace_symbols",
                summary_prefix="Find workspace symbols",
                subtitle_key="query",
                risk_level=ToolRiskLevel.READ,
                tags=("workspace", "symbols"),
            ),
            validate_input=validate_workspace_query_tool,
            execute=workspace_symbols_tool,
            origin=origin,
        ),
        ToolDefinition(
            name="workspace_references",
            description="Locate likely symbol references across the workspace.",
            input_schema={
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "path": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                    "case_sensitive": {"type": "boolean"},
                },
                "required": ["symbol"],
                "additionalProperties": False,
            },
            traits=ToolTraits(read_only=True, concurrency_safe=True),
            semantics=_read_only_tool_semantics(
                title="Find workspace references",
                operation="workspace_references",
                summary_prefix="Find workspace references",
                subtitle_key="symbol",
                risk_level=ToolRiskLevel.READ,
                tags=("workspace", "references"),
            ),
            validate_input=validate_workspace_symbol_tool,
            execute=workspace_references_tool,
            origin=origin,
        ),
        ToolDefinition(
            name="workspace_outline",
            description="Return a structural outline for a file.",
            input_schema={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                },
                "required": ["file_path"],
                "additionalProperties": False,
            },
            traits=ToolTraits(read_only=True, concurrency_safe=True),
            semantics=_read_only_tool_semantics(
                title="Inspect file outline",
                operation="workspace_outline",
                summary_prefix="Inspect file outline",
                subtitle_key="file_path",
                risk_level=ToolRiskLevel.READ,
                tags=("workspace", "outline"),
            ),
            validate_input=validate_workspace_outline_tool,
            execute=workspace_outline_tool,
            origin=origin,
        ),
        ToolDefinition(
            name="workspace_test_targets",
            description="Suggest likely verification targets for a file, symbol, or query.",
            input_schema={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                    "symbol": {"type": "string"},
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                },
                "additionalProperties": False,
            },
            traits=ToolTraits(read_only=True, concurrency_safe=True),
            semantics=_read_only_tool_semantics(
                title="Suggest test targets",
                operation="workspace_test_targets",
                summary_prefix="Suggest test targets",
                subtitle_key="file_path",
                risk_level=ToolRiskLevel.READ,
                tags=("workspace", "tests"),
            ),
            validate_input=validate_workspace_test_targets_tool,
            execute=workspace_test_targets_tool,
            origin=origin,
        ),
    )


def coding_scenario_builtin_agents() -> tuple[AgentDefinition, ...]:
    origin = DefinitionOrigin(DefinitionSource.BUNDLED)
    return (
        AgentDefinition(
            name="coding-planner",
            description="Inspect the repo and turn a coding request into a short shared task plan.",
            prompt=(
                "You are the coding planner for this workspace.\n\n"
                "Planning phase contract:\n"
                "1. Inspect the request and the existing shared task list first.\n"
                "2. Limit repo inspection to only the files needed for the current live-demo task; "
                "start with the shared task list, the failing test, and the directly related source file before expanding.\n"
                "3. Create or update a short shared task plan that the main agent can execute in order.\n"
                "4. Keep the plan observable through shared tasks instead of private notes.\n"
                "5. Return a concise planning summary that names the files inspected and the next concrete coding steps.\n\n"
                "Never edit files, never wander into unrelated files, and never claim work is verified."
            ),
            tools=("read", "glob", "grep", "workspace_*", "task_*"),
            permission_mode=PermissionMode.DEFAULT,
            max_turns=8,
            memory=MemoryScope.PROJECT,
            origin=origin,
        ),
        AgentDefinition(
            name="reviewer",
            description="Review the current mutable workspace and report risks without editing files.",
            prompt=(
                "You are the workspace reviewer.\n\n"
                "Review phase contract:\n"
                "1. Inspect the task list and any provided changed-file or shell context.\n"
                "2. Read the changed files that matter to the prompt.\n"
                "3. Focus on bugs, regressions, workflow gaps, or missing verification.\n"
                "4. End with a single summary line that starts with `review: pass` when no material issues remain, "
                "or `review: fail` when issues are still blocking confidence.\n\n"
                "Never edit files and never claim to run commands you did not run."
            ),
            tools=("read", "glob", "grep", "git_status", "git_diff", "task_list"),
            permission_mode=PermissionMode.DEFAULT,
            max_turns=4,
            memory=MemoryScope.PROJECT,
            origin=origin,
        ),
        AgentDefinition(
            name="verifier",
            description="Verify the final workspace with focused inspection, job inspection, and command checks.",
            prompt=(
                "You are the workspace verifier.\n\n"
                "Verification phase contract:\n"
                "1. Inspect the task list plus any provided changed-file or shell context for the intended outcome.\n"
                "2. Run or confirm the most relevant verification command.\n"
                "3. Inspect related jobs or shell-session state when the workflow used longer-lived shell execution.\n"
                "4. End with a single summary line that starts with `verification: pass` when the latest revision is covered, "
                "or `verification: fail` when it is not.\n\n"
                "Do not edit files."
            ),
            tools=(
                "read",
                "glob",
                "grep",
                "bash",
                "git_status",
                "git_diff",
                "workspace_test_targets",
                "task_list",
                "job_*",
            ),
            permission_mode=PermissionMode.DEFAULT,
            max_turns=4,
            memory=MemoryScope.PROJECT,
            origin=origin,
        ),
    )


def coding_scenario_builtin_skills() -> tuple[SkillDefinition, ...]:
    origin = DefinitionOrigin(DefinitionSource.BUNDLED)
    return (
        SkillDefinition(
            name="coding-loop",
            description="Enforce the main coding loop discipline in the current turn.",
            content=(
                "Follow this order in the current turn:\n\n"
                "1. Enter the planning phase first for non-trivial work by asking the `coding-planner` agent with `max_turns: 8` for a short ordered plan that inspects only the task list and the files needed for the current change.\n"
                "2. Keep the shared task list current throughout the turn.\n"
                "3. Inspect the workspace with `glob`, `grep`, `read`, or the `workspace_*` tools before editing.\n"
                "4. Make the smallest useful edit with `edit` or `write`.\n"
                "5. Use the shared `git_*` tools for repo state when they answer the question more directly than ad hoc shell usage.\n"
                "6. Use `web_research` with profile `coding` for external technical lookup; use `web_search`, `web_fetch`, and `web_find` for explicit source inspection.\n"
                "7. Run verification through `bash`, using session actions or jobs only when the command is longer-lived.\n"
                "8. Run the explicit verification phase and then the explicit review phase before the final summary.\n"
                "9. Make sure verifier output starts with `verification: pass` or `verification: fail`.\n"
                "10. Make sure reviewer output starts with `review: pass` or `review: fail`.\n"
                "11. Finish with a concise summary naming changed files, verification, review, and any remaining workflow gaps."
            ),
            user_invocable=False,
            execution_context=SkillExecutionContext.INLINE,
            origin=origin,
        ),
        SkillDefinition(
            name="review-change",
            description="Run a focused review pass in a child reviewer agent.",
            content=(
                "Run the standardized review phase for the current workspace.\n"
                "Include current tasks, changed files, and recent shell or job outcomes in the delegated prompt.\n"
                "Require the final reviewer summary to start with `review: pass` or `review: fail`."
            ),
            execution_context=SkillExecutionContext.FORK,
            agent="reviewer",
            origin=origin,
        ),
        SkillDefinition(
            name="verify-change",
            description="Run a focused verification pass in a child verifier agent.",
            content=(
                "Run the standardized verification phase for the current workspace.\n"
                "Include current tasks, changed files, and recent shell or job outcomes in the delegated prompt.\n"
                "Require the final verifier summary to start with `verification: pass` or `verification: fail`."
            ),
            execution_context=SkillExecutionContext.FORK,
            agent="verifier",
            origin=origin,
        ),
        SkillDefinition(
            name="task-discipline",
            description="Keep the shared task list accurate and actionable.",
            content=(
                "When you plan or execute work:\n\n"
                "1. Create shared tasks before substantial edits.\n"
                "2. Update task status as soon as ownership or execution changes.\n"
                "3. Keep only one task actively in progress unless the runtime plan clearly requires parallel work.\n"
                "4. Close or archive completed tasks before the final summary."
            ),
            user_invocable=False,
            execution_context=SkillExecutionContext.INLINE,
            origin=origin,
        ),
        SkillDefinition(
            name="repo-onboard",
            description="Inspect the repo before starting an unfamiliar task.",
            content=(
                "Before you edit an unfamiliar part of the repo:\n\n"
                "1. Read the nearest README or entrypoint files.\n"
                "2. Inspect the tests and surrounding code paths that define expected behavior.\n"
                "3. Use the shared workspace-intelligence tools when they can narrow the search faster than manual scanning.\n"
                "4. Note any commands or conventions that should guide the change."
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
            subtitle=str(tool_input.get(subtitle_key) or "workspace"),
            emphasis=ToolPresentationEmphasis.LOW,
        ),
        classifier_input=lambda tool_input, _context: ToolClassifierInput(
            operation=operation,
            summary=f"{summary_prefix}: {tool_input.get(subtitle_key) or 'workspace'}",
            risk_level=risk_level,
            side_effects=False,
            tags=tags,
        ),
    )


__all__ = [
    "coding_scenario_builtin_agents",
    "coding_scenario_builtin_skills",
    "shared_git_builtin_tools",
    "shared_workspace_intelligence_builtin_tools",
]
