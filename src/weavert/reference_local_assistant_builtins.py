from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .builtins.definition_helpers import static_semantics
from .definitions import (
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
    ValidationOutcome,
)
from .tool_runtime import ToolContext, maybe_await

LOCAL_ASSISTANT_BROWSER_TOOLS = (
    "browser_snapshot",
    "browser_stage_navigation",
    "browser_stage_interaction",
)
LOCAL_ASSISTANT_LOCAL_OS_TOOLS = (
    "local_os_snapshot",
    "local_os_stage_file_change",
    "local_os_stage_process_launch",
    "local_os_stage_notification",
)
LOCAL_ASSISTANT_PIM_TOOLS = (
    "pim_list_agenda",
    "pim_lookup_contacts",
    "pim_stage_calendar_event",
    "pim_stage_reminder",
    "pim_stage_task",
)
LOCAL_ASSISTANT_SCENARIO_AGENTS = (
    "assistant-planner",
    "assistant-action-worker",
    "assistant-recovery",
)
LOCAL_ASSISTANT_SCENARIO_SKILLS = (
    "safe-action-check",
    "daily-brief",
    "resume-interrupted-task",
    "research-and-act",
)

LOCAL_ASSISTANT_BROWSER_HOST_FACET = "weavert.local_assistant.bridge.browser"
LOCAL_ASSISTANT_LOCAL_OS_HOST_FACET = "weavert.local_assistant.bridge.local_os"
LOCAL_ASSISTANT_PIM_HOST_FACET = "weavert.local_assistant.bridge.pim"
_WHOLE_FACET_MAPPING_ACTIONS = frozenset(
    {
        ("browser", "snapshot"),
        ("local_os", "snapshot"),
        ("pim", "agenda"),
    }
)


def local_assistant_browser_bridge_builtin_tools() -> tuple[ToolDefinition, ...]:
    origin = DefinitionOrigin(DefinitionSource.BUNDLED)
    return (
        ToolDefinition(
            name="browser_snapshot",
            description="Describe the browser state that an app-owned host may expose to the assistant.",
            input_schema={
                "type": "object",
                "properties": {
                    "focus_url": {"type": "string"},
                    "include_recent_tabs": {"type": "boolean"},
                    "include_page_summary": {"type": "boolean"},
                },
                "additionalProperties": False,
            },
            traits=ToolTraits(read_only=True, concurrency_safe=True),
            semantics=_read_only_bridge_semantics(
                title="Inspect browser bridge state",
                operation="browser_snapshot",
                summary_prefix="Inspect browser bridge state",
                subtitle_key="focus_url",
                tags=("assistant", "browser", "snapshot"),
            ),
            execute=_host_bridge_required_executor(
                bridge_family="browser",
                action="snapshot",
                tool_name="browser_snapshot",
                expected_host_facet=LOCAL_ASSISTANT_BROWSER_HOST_FACET,
            ),
            metadata=_bridge_tool_metadata(
                bridge_family="browser",
                expected_host_facet=LOCAL_ASSISTANT_BROWSER_HOST_FACET,
            ),
            origin=origin,
        ),
        ToolDefinition(
            name="browser_stage_navigation",
            description="Stage a browser navigation request for app-owned approval and execution.",
            input_schema={
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "reason": {"type": "string"},
                    "open_in": {"type": "string", "enum": ["current_tab", "new_tab"]},
                },
                "required": ["url"],
                "additionalProperties": False,
            },
            traits=ToolTraits(concurrency_safe=True),
            semantics=_staged_bridge_semantics(
                title="Stage browser navigation",
                operation="browser_stage_navigation",
                summary_prefix="Stage browser navigation",
                subtitle_key="url",
                risk_level=ToolRiskLevel.WRITE,
                tags=("assistant", "browser", "navigation"),
            ),
            validate_input=lambda tool_input, _context: _require_non_empty_string(tool_input, "url"),
            execute=_staged_bridge_executor(
                bridge_family="browser",
                action="navigation",
                tool_name="browser_stage_navigation",
                expected_host_facet=LOCAL_ASSISTANT_BROWSER_HOST_FACET,
            ),
            metadata=_bridge_tool_metadata(
                bridge_family="browser",
                expected_host_facet=LOCAL_ASSISTANT_BROWSER_HOST_FACET,
            ),
            origin=origin,
        ),
        ToolDefinition(
            name="browser_stage_interaction",
            description="Stage a browser click, form-fill, or extraction step for explicit host mediation.",
            input_schema={
                "type": "object",
                "properties": {
                    "action": {"type": "string"},
                    "target": {"type": "string"},
                    "text": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["action", "target"],
                "additionalProperties": False,
            },
            traits=ToolTraits(concurrency_safe=True),
            semantics=_staged_bridge_semantics(
                title="Stage browser interaction",
                operation="browser_stage_interaction",
                summary_prefix="Stage browser interaction",
                subtitle_key="target",
                risk_level=ToolRiskLevel.WRITE,
                tags=("assistant", "browser", "interaction"),
            ),
            validate_input=lambda tool_input, _context: _require_fields(tool_input, "action", "target"),
            execute=_staged_bridge_executor(
                bridge_family="browser",
                action="interaction",
                tool_name="browser_stage_interaction",
                expected_host_facet=LOCAL_ASSISTANT_BROWSER_HOST_FACET,
            ),
            metadata=_bridge_tool_metadata(
                bridge_family="browser",
                expected_host_facet=LOCAL_ASSISTANT_BROWSER_HOST_FACET,
            ),
            origin=origin,
        ),
    )


def local_assistant_local_os_bridge_builtin_tools() -> tuple[ToolDefinition, ...]:
    origin = DefinitionOrigin(DefinitionSource.BUNDLED)
    return (
        ToolDefinition(
            name="local_os_snapshot",
            description="Describe staged local-OS surfaces that an app-owned host may materialize.",
            input_schema={
                "type": "object",
                "properties": {
                    "topics": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": ["files", "clipboard", "notifications", "processes"],
                        },
                    }
                },
                "additionalProperties": False,
            },
            traits=ToolTraits(read_only=True, concurrency_safe=True),
            semantics=_read_only_bridge_semantics(
                title="Inspect local OS bridge state",
                operation="local_os_snapshot",
                summary_prefix="Inspect local OS bridge state",
                subtitle_key="topics",
                tags=("assistant", "local-os", "snapshot"),
            ),
            execute=_host_bridge_required_executor(
                bridge_family="local_os",
                action="snapshot",
                tool_name="local_os_snapshot",
                expected_host_facet=LOCAL_ASSISTANT_LOCAL_OS_HOST_FACET,
            ),
            metadata=_bridge_tool_metadata(
                bridge_family="local_os",
                expected_host_facet=LOCAL_ASSISTANT_LOCAL_OS_HOST_FACET,
            ),
            origin=origin,
        ),
        ToolDefinition(
            name="local_os_stage_file_change",
            description="Stage a local file mutation request without taking autonomous write ownership.",
            input_schema={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                    "action": {"type": "string", "enum": ["create", "update", "append", "delete"]},
                    "summary": {"type": "string"},
                },
                "required": ["file_path", "action", "summary"],
                "additionalProperties": False,
            },
            traits=ToolTraits(concurrency_safe=True),
            semantics=_staged_bridge_semantics(
                title="Stage local file change",
                operation="local_os_stage_file_change",
                summary_prefix="Stage local file change",
                subtitle_key="file_path",
                risk_level=ToolRiskLevel.WRITE,
                tags=("assistant", "local-os", "file"),
            ),
            validate_input=lambda tool_input, _context: _require_fields(
                tool_input,
                "file_path",
                "action",
                "summary",
            ),
            execute=_staged_bridge_executor(
                bridge_family="local_os",
                action="file_change",
                tool_name="local_os_stage_file_change",
                expected_host_facet=LOCAL_ASSISTANT_LOCAL_OS_HOST_FACET,
            ),
            metadata=_bridge_tool_metadata(
                bridge_family="local_os",
                expected_host_facet=LOCAL_ASSISTANT_LOCAL_OS_HOST_FACET,
            ),
            origin=origin,
        ),
        ToolDefinition(
            name="local_os_stage_process_launch",
            description="Stage a local process launch request for app-owned allowlists and approval.",
            input_schema={
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "args": {"type": "array", "items": {"type": "string"}},
                    "reason": {"type": "string"},
                },
                "required": ["command"],
                "additionalProperties": False,
            },
            traits=ToolTraits(concurrency_safe=True),
            semantics=_staged_bridge_semantics(
                title="Stage process launch",
                operation="local_os_stage_process_launch",
                summary_prefix="Stage process launch",
                subtitle_key="command",
                risk_level=ToolRiskLevel.EXEC,
                tags=("assistant", "local-os", "process"),
            ),
            validate_input=lambda tool_input, _context: _require_non_empty_string(tool_input, "command"),
            execute=_staged_bridge_executor(
                bridge_family="local_os",
                action="process_launch",
                tool_name="local_os_stage_process_launch",
                expected_host_facet=LOCAL_ASSISTANT_LOCAL_OS_HOST_FACET,
            ),
            metadata=_bridge_tool_metadata(
                bridge_family="local_os",
                expected_host_facet=LOCAL_ASSISTANT_LOCAL_OS_HOST_FACET,
            ),
            origin=origin,
        ),
        ToolDefinition(
            name="local_os_stage_notification",
            description="Stage a desktop or device notification request for app-owned delivery.",
            input_schema={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "body": {"type": "string"},
                    "urgency": {"type": "string", "enum": ["low", "normal", "high"]},
                },
                "required": ["title"],
                "additionalProperties": False,
            },
            traits=ToolTraits(concurrency_safe=True),
            semantics=_staged_bridge_semantics(
                title="Stage local notification",
                operation="local_os_stage_notification",
                summary_prefix="Stage local notification",
                subtitle_key="title",
                risk_level=ToolRiskLevel.WRITE,
                tags=("assistant", "local-os", "notification"),
            ),
            validate_input=lambda tool_input, _context: _require_non_empty_string(tool_input, "title"),
            execute=_staged_bridge_executor(
                bridge_family="local_os",
                action="notification",
                tool_name="local_os_stage_notification",
                expected_host_facet=LOCAL_ASSISTANT_LOCAL_OS_HOST_FACET,
            ),
            metadata=_bridge_tool_metadata(
                bridge_family="local_os",
                expected_host_facet=LOCAL_ASSISTANT_LOCAL_OS_HOST_FACET,
            ),
            origin=origin,
        ),
    )


def local_assistant_pim_bridge_builtin_tools() -> tuple[ToolDefinition, ...]:
    origin = DefinitionOrigin(DefinitionSource.BUNDLED)
    return (
        ToolDefinition(
            name="pim_list_agenda",
            description="Describe the agenda-oriented PIM state that an app-owned host may expose.",
            input_schema={
                "type": "object",
                "properties": {
                    "start_time": {"type": "string"},
                    "end_time": {"type": "string"},
                    "include_reminders": {"type": "boolean"},
                },
                "additionalProperties": False,
            },
            traits=ToolTraits(read_only=True, concurrency_safe=True),
            semantics=_read_only_bridge_semantics(
                title="Inspect PIM agenda state",
                operation="pim_list_agenda",
                summary_prefix="Inspect PIM agenda state",
                subtitle_key="start_time",
                tags=("assistant", "pim", "agenda"),
            ),
            execute=_host_bridge_required_executor(
                bridge_family="pim",
                action="agenda",
                tool_name="pim_list_agenda",
                expected_host_facet=LOCAL_ASSISTANT_PIM_HOST_FACET,
            ),
            metadata=_bridge_tool_metadata(
                bridge_family="pim",
                expected_host_facet=LOCAL_ASSISTANT_PIM_HOST_FACET,
            ),
            origin=origin,
        ),
        ToolDefinition(
            name="pim_lookup_contacts",
            description="Describe the contact lookup surface that an app-owned host may expose.",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "purpose": {"type": "string"},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
            traits=ToolTraits(read_only=True, concurrency_safe=True),
            semantics=_read_only_bridge_semantics(
                title="Inspect contact lookup surface",
                operation="pim_lookup_contacts",
                summary_prefix="Inspect contact lookup surface",
                subtitle_key="query",
                tags=("assistant", "pim", "contacts"),
            ),
            validate_input=lambda tool_input, _context: _require_non_empty_string(tool_input, "query"),
            execute=_host_bridge_required_executor(
                bridge_family="pim",
                action="contact_lookup",
                tool_name="pim_lookup_contacts",
                expected_host_facet=LOCAL_ASSISTANT_PIM_HOST_FACET,
            ),
            metadata=_bridge_tool_metadata(
                bridge_family="pim",
                expected_host_facet=LOCAL_ASSISTANT_PIM_HOST_FACET,
            ),
            origin=origin,
        ),
        ToolDefinition(
            name="pim_stage_calendar_event",
            description="Stage a calendar event request while leaving final account binding app-owned.",
            input_schema={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "start_time": {"type": "string"},
                    "end_time": {"type": "string"},
                    "attendees": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["title", "start_time"],
                "additionalProperties": False,
            },
            traits=ToolTraits(concurrency_safe=True),
            semantics=_staged_bridge_semantics(
                title="Stage calendar event",
                operation="pim_stage_calendar_event",
                summary_prefix="Stage calendar event",
                subtitle_key="title",
                risk_level=ToolRiskLevel.WRITE,
                tags=("assistant", "pim", "calendar"),
            ),
            validate_input=lambda tool_input, _context: _require_fields(tool_input, "title", "start_time"),
            execute=_staged_bridge_executor(
                bridge_family="pim",
                action="calendar_event",
                tool_name="pim_stage_calendar_event",
                expected_host_facet=LOCAL_ASSISTANT_PIM_HOST_FACET,
            ),
            metadata=_bridge_tool_metadata(
                bridge_family="pim",
                expected_host_facet=LOCAL_ASSISTANT_PIM_HOST_FACET,
            ),
            origin=origin,
        ),
        ToolDefinition(
            name="pim_stage_reminder",
            description="Stage a reminder change request for app-owned approval and delivery.",
            input_schema={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "due_at": {"type": "string"},
                    "notes": {"type": "string"},
                },
                "required": ["title"],
                "additionalProperties": False,
            },
            traits=ToolTraits(concurrency_safe=True),
            semantics=_staged_bridge_semantics(
                title="Stage reminder update",
                operation="pim_stage_reminder",
                summary_prefix="Stage reminder update",
                subtitle_key="title",
                risk_level=ToolRiskLevel.WRITE,
                tags=("assistant", "pim", "reminder"),
            ),
            validate_input=lambda tool_input, _context: _require_non_empty_string(tool_input, "title"),
            execute=_staged_bridge_executor(
                bridge_family="pim",
                action="reminder",
                tool_name="pim_stage_reminder",
                expected_host_facet=LOCAL_ASSISTANT_PIM_HOST_FACET,
            ),
            metadata=_bridge_tool_metadata(
                bridge_family="pim",
                expected_host_facet=LOCAL_ASSISTANT_PIM_HOST_FACET,
            ),
            origin=origin,
        ),
        ToolDefinition(
            name="pim_stage_task",
            description="Stage a task creation or update request without taking final task-store ownership.",
            input_schema={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "list_name": {"type": "string"},
                    "due_at": {"type": "string"},
                    "notes": {"type": "string"},
                },
                "required": ["title"],
                "additionalProperties": False,
            },
            traits=ToolTraits(concurrency_safe=True),
            semantics=_staged_bridge_semantics(
                title="Stage task update",
                operation="pim_stage_task",
                summary_prefix="Stage task update",
                subtitle_key="title",
                risk_level=ToolRiskLevel.WRITE,
                tags=("assistant", "pim", "task"),
            ),
            validate_input=lambda tool_input, _context: _require_non_empty_string(tool_input, "title"),
            execute=_staged_bridge_executor(
                bridge_family="pim",
                action="task",
                tool_name="pim_stage_task",
                expected_host_facet=LOCAL_ASSISTANT_PIM_HOST_FACET,
            ),
            metadata=_bridge_tool_metadata(
                bridge_family="pim",
                expected_host_facet=LOCAL_ASSISTANT_PIM_HOST_FACET,
            ),
            origin=origin,
        ),
    )


def local_assistant_scenario_builtin_agents() -> tuple[AgentDefinition, ...]:
    origin = DefinitionOrigin(DefinitionSource.BUNDLED)
    return (
        AgentDefinition(
            name="assistant-planner",
            description="Inspect staged assistant context and turn it into a host-aware action plan.",
            prompt=(
                "You are the local-assistant planner.\n\n"
                "Planning contract:\n"
                "1. Gather only staged, host-mediated context first.\n"
                "2. Use retrieval plus the read-only browser, local-OS, and PIM bridge surfaces to understand the state.\n"
                "3. Keep bridge assumptions explicit and name any missing host mediation or approval requirements.\n"
                "4. Produce an ordered plan that stays inside app-owned allowlist and audit boundaries.\n"
                "5. Never imply silent automation or direct ownership of browser, OS, or account bindings."
            ),
            tools=(
                "skill",
                "retrieve_context",
                "prepare_citations",
                "browser_snapshot",
                "local_os_snapshot",
                "pim_list_agenda",
                "pim_lookup_contacts",
                "ask_user",
            ),
            skills=("safe-action-check", "remember"),
            permission_mode=PermissionMode.DEFAULT,
            max_turns=6,
            memory=MemoryScope.PROJECT,
            origin=origin,
        ),
        AgentDefinition(
            name="assistant-action-worker",
            description="Turn approved assistant intent into explicit staged bridge requests and clear handoff notes.",
            prompt=(
                "You are the local-assistant action worker.\n\n"
                "Execution contract:\n"
                "1. Re-check the requested goal and any existing evidence before acting.\n"
                "2. Prefer read-only inspection before staging high-risk bridge requests.\n"
                "3. Use only the staged bridge tools; do not claim that the package can execute browser, OS, or PIM actions autonomously.\n"
                "4. Make approval, allowlist, and audit needs explicit in every action handoff.\n"
                "5. Leave enough context for the recovery agent to resume interrupted work."
            ),
            tools=(
                "skill",
                "retrieve_context",
                "prepare_citations",
                *LOCAL_ASSISTANT_BROWSER_TOOLS,
                *LOCAL_ASSISTANT_LOCAL_OS_TOOLS,
                *LOCAL_ASSISTANT_PIM_TOOLS,
                "ask_user",
            ),
            skills=("safe-action-check", "remember"),
            permission_mode=PermissionMode.DEFAULT,
            max_turns=6,
            memory=MemoryScope.PROJECT,
            origin=origin,
        ),
        AgentDefinition(
            name="assistant-recovery",
            description="Resume interrupted assistant work without widening staged bridge authority.",
            prompt=(
                "You are the local-assistant recovery agent.\n\n"
                "Recovery contract:\n"
                "1. Reconstruct the last known goal, staged requests, and unresolved approvals.\n"
                "2. Use retrieval and read-only bridge inspection before proposing a resume path.\n"
                "3. Preserve the same app-owned host, allowlist, and audit boundary instead of bypassing it.\n"
                "4. Return the next safe step, missing approval, or missing host binding explicitly."
            ),
            tools=(
                "skill",
                "retrieve_context",
                "prepare_citations",
                "browser_snapshot",
                "local_os_snapshot",
                "pim_list_agenda",
                "pim_lookup_contacts",
                "ask_user",
            ),
            skills=("safe-action-check", "remember"),
            permission_mode=PermissionMode.DEFAULT,
            max_turns=5,
            memory=MemoryScope.PROJECT,
            origin=origin,
        ),
    )


def local_assistant_scenario_builtin_skills() -> tuple[SkillDefinition, ...]:
    origin = DefinitionOrigin(DefinitionSource.BUNDLED)
    return (
        SkillDefinition(
            name="safe-action-check",
            description="Review a staged assistant action before it leaves the current turn.",
            content=(
                "Before staging or handing off any browser, local-OS, or PIM action:\n\n"
                "1. Restate the user goal in one sentence.\n"
                "2. Name the exact bridge surface being requested.\n"
                "3. Confirm whether the step needs approval, host binding, allowlist review, or audit annotation.\n"
                "4. If any of those are missing, stop and surface the missing boundary instead of guessing."
            ),
            user_invocable=False,
            execution_context=SkillExecutionContext.INLINE,
            origin=origin,
        ),
        SkillDefinition(
            name="daily-brief",
            description="Run a planning pass for agenda, reminders, and lightweight local context.",
            content=(
                "Run the local-assistant planning phase for a daily briefing.\n"
                "Inspect staged agenda, reminder, browser, and local context first, then summarize the next useful actions."
            ),
            execution_context=SkillExecutionContext.FORK,
            agent="assistant-planner",
            origin=origin,
        ),
        SkillDefinition(
            name="resume-interrupted-task",
            description="Resume interrupted assistant work through the dedicated recovery role.",
            content=(
                "Run the recovery phase for the latest interrupted assistant task.\n"
                "Include the last known user goal, staged action receipts, and any missing approvals or host bindings."
            ),
            execution_context=SkillExecutionContext.FORK,
            agent="assistant-recovery",
            origin=origin,
        ),
        SkillDefinition(
            name="research-and-act",
            description="Gather evidence, then stage the minimum bridge actions needed to move the task forward.",
            content=(
                "Run the local-assistant action-worker flow.\n"
                "Retrieve relevant context first, inspect any needed bridge state, then stage only the smallest host-mediated actions that the app can review."
            ),
            execution_context=SkillExecutionContext.FORK,
            agent="assistant-action-worker",
            origin=origin,
        ),
    )


def _bridge_tool_metadata(*, bridge_family: str, expected_host_facet: str) -> dict[str, Any]:
    return {
        "bridge_family": bridge_family,
        "bridge_mode": "staged",
        "expected_host_facet": expected_host_facet,
        "host_binding_owner": "app",
        "allowlist_owner": "app",
        "audit_sink_owner": "app",
    }


def _host_bridge_required_executor(
    *,
    bridge_family: str,
    action: str,
    tool_name: str,
    expected_host_facet: str,
):
    async def _execute(tool_input: dict[str, Any], _context: ToolContext) -> dict[str, Any]:
        bound_host_facet, host_facet_operation_supported, payload = await _call_bound_host_bridge(
            context=_context,
            bridge_family=bridge_family,
            action=action,
            tool_name=tool_name,
            expected_host_facet=expected_host_facet,
            tool_input=tool_input,
            staged=False,
        )
        if bound_host_facet and host_facet_operation_supported:
            return {
                **_bridge_result_metadata(
                    bridge_family=bridge_family,
                    action=action,
                    expected_host_facet=expected_host_facet,
                    tool_input=tool_input,
                    approval_required=False,
                    bound_host_facet=True,
                    host_facet_operation_supported=True,
                ),
                "status": "available",
                "bridge_state": payload,
            }
        return {
            **_bridge_result_metadata(
                bridge_family=bridge_family,
                action=action,
                expected_host_facet=expected_host_facet,
                tool_input=tool_input,
                approval_required=False,
                bound_host_facet=bound_host_facet,
                host_facet_operation_supported=host_facet_operation_supported,
            ),
            "status": "host_bridge_required",
            "app_owned_next_step": (
                "Extend the bound app-owned host facet to expose live browser, OS, or PIM state for this operation."
                if bound_host_facet
                else "Bind an app-owned host facet before exposing live browser, OS, or PIM state to this package."
            ),
        }

    return _execute


def _staged_bridge_executor(
    *,
    bridge_family: str,
    action: str,
    tool_name: str,
    expected_host_facet: str,
):
    async def _execute(tool_input: dict[str, Any], _context: ToolContext) -> dict[str, Any]:
        bound_host_facet, host_facet_operation_supported, payload = await _call_bound_host_bridge(
            context=_context,
            bridge_family=bridge_family,
            action=action,
            tool_name=tool_name,
            expected_host_facet=expected_host_facet,
            tool_input=tool_input,
            staged=True,
        )
        if bound_host_facet and host_facet_operation_supported:
            return {
                **_bridge_result_metadata(
                    bridge_family=bridge_family,
                    action=action,
                    expected_host_facet=expected_host_facet,
                    tool_input=tool_input,
                    approval_required=True,
                    bound_host_facet=True,
                    host_facet_operation_supported=True,
                ),
                "status": "staged",
                "receipt": payload,
            }
        return {
            **_bridge_result_metadata(
                bridge_family=bridge_family,
                action=action,
                expected_host_facet=expected_host_facet,
                tool_input=tool_input,
                approval_required=True,
                bound_host_facet=bound_host_facet,
                host_facet_operation_supported=host_facet_operation_supported,
            ),
            "status": "staged",
            "app_owned_next_step": (
                "The app-owned host reviews the staged request, applies final allowlists and audit policy, and decides whether to execute it."
                if not bound_host_facet
                else "The app-owned host can keep reviewing this staged request directly, or extend the bound host facet to attach a host-specific staged receipt for this operation."
            ),
        }

    return _execute


def _bridge_result_metadata(
    *,
    bridge_family: str,
    action: str,
    expected_host_facet: str,
    tool_input: Mapping[str, Any],
    approval_required: bool,
    bound_host_facet: bool,
    host_facet_operation_supported: bool,
) -> dict[str, Any]:
    return {
        "bridge_family": bridge_family,
        "action": action,
        "approval_required": approval_required,
        "host_binding_owner": "app",
        "allowlist_owner": "app",
        "audit_sink_owner": "app",
        "expected_host_facet": expected_host_facet,
        "bound_host_facet": bound_host_facet,
        "host_facet_operation_supported": host_facet_operation_supported,
        "request": _snapshot_value(tool_input),
    }


async def _call_bound_host_bridge(
    *,
    context: ToolContext,
    bridge_family: str,
    action: str,
    tool_name: str,
    expected_host_facet: str,
    tool_input: Mapping[str, Any],
    staged: bool,
) -> tuple[bool, bool, Any | None]:
    if context.runtime_services is None:
        return False, False, None
    resolution = context.runtime_services.resolve_host_facet(expected_host_facet)
    if not resolution.available or resolution.facet is None:
        return False, False, None
    facet = resolution.facet
    if not staged and isinstance(facet, Mapping):
        supported, payload = _mapping_bridge_payload(
            facet,
            bridge_family=bridge_family,
            action=action,
            tool_name=tool_name,
        )
        return True, supported, payload
    handler, generic = _resolve_host_bridge_handler(
        facet,
        tool_name=tool_name,
        action=action,
        staged=staged,
    )
    if handler is None:
        return True, False, None
    request = _snapshot_value(tool_input)
    if generic:
        payload = await maybe_await(
            handler(
                bridge_family=bridge_family,
                action=action,
                tool_name=tool_name,
                request=request,
                context=context,
            )
        )
    else:
        payload = await maybe_await(handler(request=request, context=context))
    return True, True, _snapshot_value(payload)


def _mapping_bridge_payload(
    facet: Mapping[str, Any],
    *,
    bridge_family: str,
    action: str,
    tool_name: str,
) -> tuple[bool, Any | None]:
    operations = facet.get("operations")
    candidate_mappings = [facet]
    if isinstance(operations, Mapping):
        candidate_mappings.append(operations)
    for mapping in candidate_mappings:
        for key in (tool_name, action):
            if key in mapping:
                return True, _snapshot_value(mapping[key])
    if (bridge_family, action) in _WHOLE_FACET_MAPPING_ACTIONS:
        return True, _snapshot_value(facet)
    return False, None


def _resolve_host_bridge_handler(
    facet: Any,
    *,
    tool_name: str,
    action: str,
    staged: bool,
) -> tuple[Any | None, bool]:
    candidate_names = [tool_name]
    if staged:
        candidate_names.append(f"stage_{action}")
    candidate_names.extend((action, "handle_bridge_request", "handle_request"))
    for name in candidate_names:
        handler = getattr(facet, name, None)
        if callable(handler):
            return handler, name in {"handle_bridge_request", "handle_request"}
    return None, False


def _require_non_empty_string(tool_input: Mapping[str, Any], field_name: str) -> ValidationOutcome:
    value = str(tool_input.get(field_name) or "").strip()
    if not value:
        return ValidationOutcome(False, f"{field_name} must be non-empty")
    return ValidationOutcome(True)


def _require_fields(tool_input: Mapping[str, Any], *field_names: str) -> ValidationOutcome:
    for field_name in field_names:
        outcome = _require_non_empty_string(tool_input, field_name)
        if not outcome.valid:
            return outcome
    return ValidationOutcome(True)


def _snapshot_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _snapshot_value(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_snapshot_value(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _read_only_bridge_semantics(
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
            subtitle=_tool_subtitle(tool_input, subtitle_key),
            emphasis=ToolPresentationEmphasis.LOW,
        ),
        classifier_input=lambda tool_input, _context: ToolClassifierInput(
            operation=operation,
            summary=f"{summary_prefix}: {_tool_subtitle(tool_input, subtitle_key)}",
            risk_level=ToolRiskLevel.READ,
            side_effects=False,
            tags=tags,
        ),
    )


def _staged_bridge_semantics(
    *,
    title: str,
    operation: str,
    summary_prefix: str,
    subtitle_key: str,
    risk_level: ToolRiskLevel,
    tags: tuple[str, ...],
):
    return static_semantics(
        read_only=False,
        concurrency_safe=True,
        tool_use_presentation=lambda tool_input, _context: ToolUsePresentation(
            title=title,
            subtitle=_tool_subtitle(tool_input, subtitle_key),
            emphasis=ToolPresentationEmphasis.NORMAL,
        ),
        classifier_input=lambda tool_input, _context: ToolClassifierInput(
            operation=operation,
            summary=f"{summary_prefix}: {_tool_subtitle(tool_input, subtitle_key)}",
            risk_level=risk_level,
            side_effects=True,
            tags=tags,
        ),
    )


def _tool_subtitle(tool_input: Mapping[str, Any], field_name: str) -> str:
    value = tool_input.get(field_name)
    if isinstance(value, list):
        return ", ".join(str(item) for item in value) or "assistant bridge"
    text = str(value or "").strip()
    return text or "assistant bridge"


__all__ = [
    "LOCAL_ASSISTANT_BROWSER_HOST_FACET",
    "LOCAL_ASSISTANT_BROWSER_TOOLS",
    "LOCAL_ASSISTANT_LOCAL_OS_HOST_FACET",
    "LOCAL_ASSISTANT_LOCAL_OS_TOOLS",
    "LOCAL_ASSISTANT_PIM_HOST_FACET",
    "LOCAL_ASSISTANT_PIM_TOOLS",
    "LOCAL_ASSISTANT_SCENARIO_AGENTS",
    "LOCAL_ASSISTANT_SCENARIO_SKILLS",
    "local_assistant_browser_bridge_builtin_tools",
    "local_assistant_local_os_bridge_builtin_tools",
    "local_assistant_pim_bridge_builtin_tools",
    "local_assistant_scenario_builtin_agents",
    "local_assistant_scenario_builtin_skills",
]
