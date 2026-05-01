from __future__ import annotations

import asyncio
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from demos._shared.bootstrap import PROJECT_ROOT

from weavert.child_result_projection import project_child_run_record
from weavert.contracts import MessageRole, RuntimeMessage, ToolResultBlock
from weavert.definitions import DefinitionSource
from weavert.runtime_kernel import DefinitionSourcePaths, RuntimeConfig, RuntimeDistribution, assemble_runtime
from weavert.session_runtime import InboundEvent, InboundEventType
from weavert.turn_engine.engine import TurnStreamEventType

from .host import ApprovalRecord, CodeAssistantHost

DEFAULT_SESSION_PREFIX = "code-assistant"
DEFAULT_PROMPT = """Work in the current mini repo.

Goal:
1. Make the greeting tests pass by updating the default greeting to \"Hello, WeaveRT.\".
2. Add a new file at notes/live_demo.md with one short sentence describing the change.
3. Run `python3 -m unittest discover -s tests`.
4. Ask the `reviewer` agent to review the final workspace.
5. Ask the `verifier` agent to confirm the verification result.

Keep the shared task list current while you work.
"""


@dataclass(frozen=True, slots=True)
class CodeAssistantLayout:
    demo_root: Path
    state_root: Path

    @property
    def fixture_root(self) -> Path:
        return self.demo_root / "fixtures" / "mini_repo"

    @property
    def workspace_root(self) -> Path:
        return self.state_root / "mini_repo"


@dataclass(frozen=True, slots=True)
class RunReport:
    session_id: str
    workspace_root: Path
    fixture_root: Path
    distribution: str
    default_model_route: str | None
    persistence_profile: dict[str, Any]
    messages: tuple[RuntimeMessage, ...]
    final_text: str
    approvals: tuple[ApprovalRecord, ...]
    child_runs: tuple[dict[str, Any], ...]
    task_list_id: str
    task_list: dict[str, Any]
    transcript_path: Path
    child_run_index_path: Path
    memory_root: Path
    notification_texts: tuple[str, ...]
    terminal_stop_reason: str | None
    terminal_metadata: dict[str, Any]
    workflow_gaps: tuple[str, ...]
    ok: bool
    error_message: str | None = None


@dataclass(frozen=True, slots=True)
class InspectReport:
    workspace_exists: bool
    workspace_root: Path
    fixture_root: Path
    state_root: Path
    distribution: str | None
    default_model_route: str | None
    persistence_profile: dict[str, Any]
    transcript_sessions: tuple[dict[str, Any], ...]
    child_run_sessions: tuple[dict[str, Any], ...]
    child_run_records: tuple[dict[str, Any], ...]
    task_lists: tuple[dict[str, Any], ...]
    memory_root: Path | None
    memory_documents: int


def default_layout(*, state_root: Path | None = None) -> CodeAssistantLayout:
    demo_root = PROJECT_ROOT / "demos" / "apps" / "code_assistant"
    return CodeAssistantLayout(
        demo_root=demo_root,
        state_root=state_root or (demo_root / "state"),
    )


def reset_demo_state(*, layout: CodeAssistantLayout | None = None) -> Path:
    resolved_layout = layout or default_layout()
    workspace_root = resolved_layout.workspace_root
    workspace_root.parent.mkdir(parents=True, exist_ok=True)
    if workspace_root.exists():
        shutil.rmtree(workspace_root)
    shutil.copytree(resolved_layout.fixture_root, workspace_root)
    return workspace_root


def ensure_demo_state(*, layout: CodeAssistantLayout | None = None) -> Path:
    resolved_layout = layout or default_layout()
    workspace_root = resolved_layout.workspace_root
    if workspace_root.exists():
        return workspace_root
    return reset_demo_state(layout=resolved_layout)


def assemble_demo_runtime(
    *,
    layout: CodeAssistantLayout | None = None,
    model_client: Any = None,
):
    resolved_layout = layout or default_layout()
    workspace_root = ensure_demo_state(layout=resolved_layout)
    config = RuntimeConfig(
        working_directory=workspace_root,
        distribution=RuntimeDistribution.FULL,
        discovery_sources=(
            DefinitionSourcePaths(DefinitionSource.PROJECT, workspace_root / ".weavert"),
        ),
        model_client=model_client,
    )
    return assemble_runtime(config)


async def run_demo(
    *,
    prompt: str = DEFAULT_PROMPT,
    session_id: str | None = None,
    auto_approve: bool = False,
    validate_workflow: bool = True,
    layout: CodeAssistantLayout | None = None,
    model_client: Any = None,
    input_reader=input,
    output_writer=print,
) -> RunReport:
    resolved_layout = layout or default_layout()
    workspace_root = ensure_demo_state(layout=resolved_layout)
    runtime = assemble_demo_runtime(layout=resolved_layout, model_client=model_client)
    host = CodeAssistantHost(
        name="code-assistant-host",
        auto_approve=auto_approve,
        input_reader=input_reader,
        output_writer=output_writer,
    )
    agent = runtime.kernel.agent_registry.get("code-assistant")
    if agent is None:
        raise RuntimeError("Missing workspace-local code-assistant agent definition")
    resolved_session_id = session_id or f"{DEFAULT_SESSION_PREFIX}-{uuid4().hex[:8]}"

    final_messages: list[RuntimeMessage] = []
    terminal_stop_reason: str | None = None
    terminal_metadata: dict[str, Any] = {}

    async with runtime.bind_host(host) as bound:
        session = bound.create_session(
            session_id=resolved_session_id,
            agent_name="code-assistant",
            cwd=workspace_root,
        )
        await session.start()
        session.enqueue_event(InboundEvent(InboundEventType.USER_PROMPT, prompt))
        async for event in session.stream_until_idle():
            if event.event_type == TurnStreamEventType.MESSAGE and event.message is not None:
                final_messages.append(event.message)
            elif event.event_type == TurnStreamEventType.TERMINAL and event.terminal is not None:
                terminal_stop_reason = event.terminal.stop_reason
                terminal_metadata = dict(event.terminal.metadata)
        await session.close(final_status=_final_status(terminal_metadata, terminal_stop_reason))
        await _wait_for_background_memory(runtime=runtime, session=session)
        task_list_id = await runtime.resolve_task_list_id(session_id=resolved_session_id)
        task_list = await runtime.get_task_list(
            list_id=task_list_id,
            include_archived=True,
        )

    memory_context = _memory_context(runtime=runtime, agent=agent, session_id=resolved_session_id, cwd=workspace_root)
    transcript_path = workspace_root / ".weavert" / "transcripts" / f"{resolved_session_id}.jsonl"
    child_run_index_path = workspace_root / ".weavert" / "child_runs" / "sessions" / f"{resolved_session_id}.json"
    final_text = _last_assistant_text(final_messages)
    error_message = _terminal_error_message(terminal_metadata)
    workflow_gaps: tuple[str, ...] = ()
    if error_message is None and validate_workflow:
        workflow_gaps = _workflow_validation_gaps(
            messages=final_messages,
            approvals=host.approvals,
            child_runs=host.child_run_events,
            task_list=task_list,
            final_text=final_text,
        )
    return RunReport(
        session_id=resolved_session_id,
        workspace_root=workspace_root,
        fixture_root=resolved_layout.fixture_root,
        distribution=runtime.kernel.distribution,
        default_model_route=runtime.kernel.config.default_model_route,
        persistence_profile=runtime.query_persistence_profile(),
        messages=tuple(final_messages),
        final_text=final_text,
        approvals=tuple(host.approvals),
        child_runs=tuple(host.child_run_events),
        task_list_id=task_list_id,
        task_list=task_list,
        transcript_path=transcript_path,
        child_run_index_path=child_run_index_path,
        memory_root=memory_context.memory_root,
        notification_texts=tuple(message.text for message in host.notifications if message.text),
        terminal_stop_reason=terminal_stop_reason,
        terminal_metadata=terminal_metadata,
        workflow_gaps=workflow_gaps,
        ok=error_message is None and not workflow_gaps,
        error_message=error_message or _workflow_error_message(workflow_gaps),
    )


def inspect_demo(*, layout: CodeAssistantLayout | None = None) -> InspectReport:
    resolved_layout = layout or default_layout()
    workspace_root = resolved_layout.workspace_root
    if not workspace_root.exists():
        return InspectReport(
            workspace_exists=False,
            workspace_root=workspace_root,
            fixture_root=resolved_layout.fixture_root,
            state_root=resolved_layout.state_root,
            distribution=None,
            default_model_route=None,
            persistence_profile={},
            transcript_sessions=(),
            child_run_sessions=(),
            child_run_records=(),
            task_lists=(),
            memory_root=None,
            memory_documents=0,
        )

    runtime = assemble_demo_runtime(layout=resolved_layout)
    agent = runtime.kernel.agent_registry.get("code-assistant")
    transcript_sessions = _transcript_sessions(workspace_root)
    child_run_records = asyncio.run(_child_run_records(runtime=runtime, session_ids=_session_ids(workspace_root)))
    child_run_sessions = _summarize_child_run_sessions(child_run_records)
    task_lists = asyncio.run(runtime.list_task_lists())
    memory_root = None
    memory_documents = 0
    if agent is not None:
        memory_context = _memory_context(
            runtime=runtime,
            agent=agent,
            session_id=transcript_sessions[0]["session_id"] if transcript_sessions else "inspect-preview",
            cwd=workspace_root,
        )
        memory_root = memory_context.memory_root
        if memory_root.exists():
            memory_documents = sum(1 for path in memory_root.rglob("*.md") if path.is_file())

    return InspectReport(
        workspace_exists=True,
        workspace_root=workspace_root,
        fixture_root=resolved_layout.fixture_root,
        state_root=resolved_layout.state_root,
        distribution=runtime.kernel.distribution,
        default_model_route=runtime.kernel.config.default_model_route,
        persistence_profile=runtime.query_persistence_profile(),
        transcript_sessions=tuple(transcript_sessions),
        child_run_sessions=tuple(child_run_sessions),
        child_run_records=tuple(child_run_records),
        task_lists=tuple(task_lists),
        memory_root=memory_root,
        memory_documents=memory_documents,
    )


def _memory_context(*, runtime, agent, session_id: str, cwd: Path):
    memory_service = runtime.services.resolve_memory_service()
    if memory_service is None or not hasattr(memory_service, "resolve_context"):
        raise RuntimeError("The full runtime demo requires a memory service")
    return memory_service.resolve_context(session_id=session_id, agent=agent, cwd=cwd)


async def _wait_for_background_memory(*, runtime, session) -> None:
    memory_service = runtime.services.resolve_memory_service()
    if memory_service is None or not hasattr(memory_service, "wait_for_background_consolidation"):
        return
    seen: set[str] = set()
    extraction_ids = session.state.metadata.get("background_memory_tasks")
    if isinstance(extraction_ids, list) and hasattr(memory_service, "wait_for_background_extraction"):
        for task_id in extraction_ids:
            normalized = str(task_id).strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            await memory_service.wait_for_background_extraction(normalized)
    consolidation_ids = session.state.metadata.get("background_memory_consolidation_tasks")
    if not isinstance(consolidation_ids, list):
        return
    for task_id in consolidation_ids:
        normalized = str(task_id).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        await memory_service.wait_for_background_consolidation(normalized)


async def _child_run_records(*, runtime, session_ids: tuple[str, ...]) -> tuple[dict[str, Any], ...]:
    projected: list[dict[str, Any]] = []
    for session_id in session_ids:
        records = await runtime.agent_runtime.run_store.list_by_session(session_id)
        if not records:
            continue
        for record in records:
            projection = project_child_run_record(record)
            projection["session_id"] = session_id
            projected.append(projection)
    return tuple(projected)


def _summarize_child_run_sessions(child_run_records: tuple[dict[str, Any], ...]) -> tuple[dict[str, Any], ...]:
    grouped: dict[str, dict[str, Any]] = {}
    for record in child_run_records:
        session_id = str(record.get("session_id") or "").strip()
        if not session_id:
            continue
        summary = grouped.setdefault(
            session_id,
            {
                "session_id": session_id,
                "count": 0,
                "agents": [],
                "statuses": [],
            },
        )
        summary["count"] += 1
        summary["agents"].append(record.get("agent"))
        summary["statuses"].append(record.get("status"))
    return tuple(grouped[session_id] for session_id in grouped)


def _session_ids(workspace_root: Path) -> tuple[str, ...]:
    transcripts_root = workspace_root / ".weavert" / "transcripts"
    if not transcripts_root.exists():
        return ()
    session_files = sorted(transcripts_root.glob("*.jsonl"), key=lambda path: path.stat().st_mtime, reverse=True)
    return tuple(path.stem for path in session_files)


def _transcript_sessions(workspace_root: Path) -> list[dict[str, Any]]:
    transcripts_root = workspace_root / ".weavert" / "transcripts"
    if not transcripts_root.exists():
        return []
    sessions: list[dict[str, Any]] = []
    for path in sorted(transcripts_root.glob("*.jsonl"), key=lambda item: item.stat().st_mtime, reverse=True):
        line_count = sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
        sessions.append(
            {
                "session_id": path.stem,
                "path": path,
                "entries": line_count,
            }
        )
    return sessions


def _final_status(terminal_metadata: dict[str, Any], terminal_stop_reason: str | None) -> str:
    if terminal_metadata.get("failure_class") not in {None, "", "none"}:
        return "failed"
    if terminal_stop_reason == "interrupted":
        return "interrupted"
    if terminal_stop_reason == "blocked":
        return "stopped"
    return "completed"


def _last_assistant_text(messages: list[RuntimeMessage]) -> str:
    for message in reversed(messages):
        if message.role == MessageRole.ASSISTANT and message.text:
            return message.text
    return ""


def _terminal_error_message(terminal_metadata: dict[str, Any]) -> str | None:
    failure_class = str(terminal_metadata.get("failure_class") or "").strip()
    if not failure_class or failure_class == "none":
        return None
    error = str(terminal_metadata.get("error") or failure_class).strip()
    return error or failure_class


def _workflow_validation_gaps(
    *,
    messages: list[RuntimeMessage],
    approvals: list[ApprovalRecord],
    child_runs: list[dict[str, Any]],
    task_list: dict[str, Any],
    final_text: str,
) -> tuple[str, ...]:
    gaps: list[str] = []
    successful_tools = _successful_tool_names(messages)
    required_tools = {
        "skill": "the workflow skill did not run",
        "task_create": "shared task planning did not create any tasks",
        "task_list": "the shared task list was never inspected",
        "grep": "the workflow never used grep before editing",
        "read": "the workflow never used read before editing",
        "edit": "the workflow never used edit",
        "write": "the workflow never used write",
        "bash": "the workflow never used bash verification",
    }
    for tool_name, message in required_tools.items():
        if tool_name not in successful_tools:
            gaps.append(message)

    skill_result = _find_skill_result(messages, skill_name="v1-code-workflow")
    if skill_result is None:
        gaps.append("the workspace-local v1-code-workflow skill was not applied")
    elif skill_result.get("mode") != "inline":
        gaps.append("the workspace-local v1-code-workflow skill did not run inline")

    approval_names = {approval.name for approval in approvals}
    for tool_name in ("edit", "write", "bash"):
        if tool_name not in approval_names:
            gaps.append(f"host approval for {tool_name} was never recorded")

    child_statuses: dict[str, str] = {}
    for child in child_runs:
        agent = str(child.get("agent") or "").strip()
        status = str(child.get("status") or "").strip()
        if agent:
            child_statuses[agent] = status
    for agent_name in ("reviewer", "verifier"):
        status = child_statuses.get(agent_name)
        if status is None:
            gaps.append(f"the {agent_name} child run never executed")
        elif status != "completed":
            gaps.append(f"the {agent_name} child run ended with status '{status}'")

    tasks = task_list.get("tasks", ())
    if not isinstance(tasks, list) or not tasks:
        gaps.append("the shared task list is empty")

    if not final_text.strip():
        gaps.append("the assistant did not return a final summary")

    return tuple(gaps)


def _successful_tool_names(messages: list[RuntimeMessage]) -> set[str]:
    successful: set[str] = set()
    for entry in _tool_result_entries(messages):
        if str(entry.get("status") or "").strip() == "success":
            tool_name = str(entry.get("tool_name") or "").strip()
            if tool_name:
                successful.add(tool_name)
    return successful


def _tool_result_entries(messages: list[RuntimeMessage]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for message in messages:
        raw_entries = message.metadata.get("tool_results", ())
        if not isinstance(raw_entries, list):
            continue
        for entry in raw_entries:
            if isinstance(entry, dict):
                entries.append(entry)
    return entries


def _find_skill_result(messages: list[RuntimeMessage], *, skill_name: str) -> dict[str, Any] | None:
    for message in messages:
        for block in message.content:
            if not isinstance(block, ToolResultBlock) or not isinstance(block.content, dict):
                continue
            if str(block.content.get("skill") or "").strip() == skill_name:
                return block.content
    return None


def _workflow_error_message(workflow_gaps: tuple[str, ...]) -> str | None:
    if not workflow_gaps:
        return None
    return "Workflow validation failed: " + "; ".join(workflow_gaps)


__all__ = [
    "CodeAssistantLayout",
    "DEFAULT_PROMPT",
    "InspectReport",
    "RunReport",
    "assemble_demo_runtime",
    "default_layout",
    "ensure_demo_state",
    "inspect_demo",
    "reset_demo_state",
    "run_demo",
]
