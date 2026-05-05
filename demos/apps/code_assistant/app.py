from __future__ import annotations

import asyncio
import os
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from demos._shared.bootstrap import PROJECT_ROOT

from weavert.agent_execution import AgentRunRecord
from weavert.child_result_projection import project_child_run_record
from weavert.contracts import MessageRole, RuntimeMessage, ToolResultBlock
from weavert.definitions import DefinitionSource
from weavert.result_projections import child_summary, final_assistant_text, latest_skill_outcome
from weavert.runtime_kernel import (
    BuiltinPackConfig,
    DefinitionSourcePaths,
    RuntimeConfig,
    assemble_runtime,
)
from weavert.scenario_runtime_packs import reference_scenario_runtime_pack_manifests
from weavert.session_runtime import InboundEvent, InboundEventType
from weavert.turn_engine.engine import TurnStreamEventType

from .builtin_overrides import (
    build_code_assistant_bash_replacement,
    reconcile_background_shell_jobs,
)
from .host import ApprovalRecord, CodeAssistantHost

DEFAULT_SESSION_PREFIX = "code-assistant"
CODE_ASSISTANT_STATE_ROOT_ENV = "WEAVERT_CODE_ASSISTANT_STATE_ROOT"
DEFAULT_PROMPT = """Work in the current mini repo.

Goal:
1. Apply the `coding-loop` skill at the start of the task.
2. Ask the `coding-planner` agent with `max_turns: 8` to inspect only the shared task list plus the files needed for this change, leave a short visible shared task plan, and return a concise planning summary.
3. Make the greeting tests pass by updating the default greeting to "Hello, WeaveRT.".
4. Add a new file at notes/live_demo.md with one short sentence describing the change.
5. Run `python3 -m unittest discover -s tests`.
6. Ask the `reviewer` agent to review the final workspace.
7. Ask the `verifier` agent to confirm the verification result.

Keep the shared task list current while you work, and treat planner-created tasks as the visible plan you execute.
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
    workflow_ledger: "WorkflowLedger"
    workflow_gaps: tuple[str, ...]
    workflow_advisories: tuple[str, ...]
    workflow_warnings: tuple[str, ...]
    ok: bool
    error_message: str | None = None


@dataclass(frozen=True, slots=True)
class ShellReport:
    session_id: str
    workspace_root: Path
    fixture_root: Path
    distribution: str
    default_model_route: str | None
    persistence_profile: dict[str, Any]
    transcript_path: Path
    child_run_index_path: Path
    memory_root: Path
    approvals: tuple[ApprovalRecord, ...]
    child_runs: tuple[dict[str, Any], ...]
    notification_texts: tuple[str, ...]
    prompt_count: int
    local_commands: tuple[str, ...]
    job_watch_events: tuple[dict[str, Any], ...]
    task_watch_events: tuple[dict[str, Any], ...]
    workflow_events: tuple[dict[str, Any], ...]
    terminal_stop_reason: str | None
    terminal_metadata: dict[str, Any]
    workflow_ledger: "WorkflowLedger"
    workflow_warnings: tuple[str, ...]
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
    changed_files: tuple[str, ...]
    workflow_ledger: "WorkflowLedger | None"
    memory_root: Path | None
    memory_documents: int
    highlighted_session_id: str | None = None
    highlighted_task_list_id: str | None = None


@dataclass(frozen=True, slots=True)
class WorkflowLedger:
    change_revision: int
    verified_revision: int
    reviewed_revision: int
    current_state: str
    last_verification_outcome: str | None = None
    last_review_outcome: str | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "change_revision": self.change_revision,
            "verified_revision": self.verified_revision,
            "reviewed_revision": self.reviewed_revision,
            "current_state": self.current_state,
            "last_verification_outcome": self.last_verification_outcome,
            "last_review_outcome": self.last_review_outcome,
        }


@dataclass(frozen=True, slots=True)
class WorkflowValidationResult:
    workflow_gaps: tuple[str, ...]
    workflow_advisories: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ToolResultEvent:
    scope: str
    agent_name: str | None
    run_id: str | None
    tool_name: str
    status: str
    created_at: datetime
    message_index: int
    result_index: int
    content: dict[str, Any]


@dataclass(frozen=True, slots=True)
class PlanningOutcome:
    classification: str
    terminal_status: str | None
    summary: str | None
    visible_task_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class InspectionOutcome:
    satisfied: bool
    late_only: bool = False


@dataclass(frozen=True, slots=True)
class PromptOutcome:
    messages: tuple[RuntimeMessage, ...]
    terminal_stop_reason: str | None
    terminal_metadata: dict[str, Any]
    turn_id: str | None


@dataclass(frozen=True, slots=True)
class LocalShellCommand:
    name: str
    argument: str | None = None


@dataclass(frozen=True, slots=True)
class LocalCommandOutcome:
    exit_shell: bool = False
    dispatch_prompt: str | None = None
    resume_session_id: str | None = None


def default_layout(*, state_root: Path | None = None) -> CodeAssistantLayout:
    demo_root = PROJECT_ROOT / "demos" / "apps" / "code_assistant"
    env_state_root = os.environ.get(CODE_ASSISTANT_STATE_ROOT_ENV, "").strip()
    return CodeAssistantLayout(
        demo_root=demo_root,
        state_root=state_root or (Path(env_state_root).expanduser() if env_state_root else demo_root / "state"),
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
    config = RuntimeConfig.for_host_bound(workspace_root)
    # The app shell stays workspace-local while the reusable coding workflow stack comes from packages.
    config.discovery_sources = (
        DefinitionSourcePaths(DefinitionSource.PROJECT, workspace_root / ".weavert"),
    )
    config.extra_package_manifests = reference_scenario_runtime_pack_manifests()
    config.requested_packages.add("weavert-scenario-coding")
    config.builtins = BuiltinPackConfig(
        tool_replacements={"bash": build_code_assistant_bash_replacement()},
    )
    config.model_client = model_client
    runtime = assemble_runtime(config)
    reconcile_background_shell_jobs(runtime.services.job_service)
    return runtime


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
    host.activate_session(resolved_session_id)

    async with runtime.bind_host(host) as bound:
        session = bound.create_session(
            session_id=resolved_session_id,
            agent_name="code-assistant",
            cwd=workspace_root,
        )
        await _prepare_session(session)
        outcome = await _run_session_prompt(session=session, prompt=prompt)
        await session.close(
            final_status=_final_status(outcome.terminal_metadata, outcome.terminal_stop_reason)
        )
        await _wait_for_background_memory(runtime=runtime, session=session)
        task_list_id = await bound.resolve_task_list_id(session_id=resolved_session_id)
        task_list = await bound.get_task_list(
            list_id=task_list_id,
            include_archived=True,
        )
        session_messages = tuple(session.messages)

    memory_context = _memory_context(runtime=runtime, agent=agent, session_id=resolved_session_id, cwd=workspace_root)
    transcript_path = workspace_root / ".weavert" / "transcripts" / f"{resolved_session_id}.jsonl"
    child_run_index_path = workspace_root / ".weavert" / "child_runs" / "sessions" / f"{resolved_session_id}.json"
    child_run_records = tuple(await runtime.agent_runtime.run_store.list_by_session(resolved_session_id))
    session_child_runs = _project_child_runs(child_run_records, session_id=resolved_session_id)
    final_text = _last_assistant_text(list(outcome.messages))
    error_message = _terminal_error_message(outcome.terminal_metadata)
    workflow_ledger = await _workflow_ledger_for_session(
        runtime=runtime,
        session_id=resolved_session_id,
        live_messages=session_messages,
    )
    workflow_warnings = _workflow_warnings_for_state(
        workflow_ledger,
        include_summary_warning=bool(final_text),
    )
    workflow_gaps: tuple[str, ...] = ()
    workflow_advisories: tuple[str, ...] = ()
    if error_message is None and validate_workflow:
        validation = _workflow_validation_result(
            messages=list(outcome.messages),
            approvals=[approval for approval in host.approvals if approval.session_id == resolved_session_id],
            child_run_records=list(child_run_records),
            task_list=task_list,
            final_text=final_text,
            workflow_ledger=workflow_ledger,
            current_turn_id=outcome.turn_id,
        )
        workflow_gaps = validation.workflow_gaps
        workflow_advisories = validation.workflow_advisories
    return RunReport(
        session_id=resolved_session_id,
        workspace_root=workspace_root,
        fixture_root=resolved_layout.fixture_root,
        distribution=runtime.kernel.distribution,
        default_model_route=runtime.kernel.config.default_model_route,
        persistence_profile=runtime.query_persistence_profile(),
        messages=outcome.messages,
        final_text=final_text,
        approvals=tuple(host.approvals),
        child_runs=session_child_runs,
        task_list_id=task_list_id,
        task_list=task_list,
        transcript_path=transcript_path,
        child_run_index_path=child_run_index_path,
        memory_root=memory_context.memory_root,
        notification_texts=tuple(message.text for message in host.notifications if message.text),
        terminal_stop_reason=outcome.terminal_stop_reason,
        terminal_metadata=outcome.terminal_metadata,
        workflow_ledger=workflow_ledger,
        workflow_gaps=workflow_gaps,
        workflow_advisories=workflow_advisories,
        workflow_warnings=workflow_warnings,
        ok=error_message is None and not workflow_gaps,
        error_message=error_message or _workflow_error_message(workflow_gaps),
    )


async def shell_demo(
    *,
    session_id: str | None = None,
    auto_approve: bool = False,
    layout: CodeAssistantLayout | None = None,
    model_client: Any = None,
    input_reader=input,
    output_writer=print,
) -> ShellReport:
    resolved_layout = layout or default_layout()
    workspace_root = ensure_demo_state(layout=resolved_layout)
    runtime = assemble_demo_runtime(layout=resolved_layout, model_client=model_client)
    host = CodeAssistantHost(
        name="code-assistant-shell-host",
        auto_approve=auto_approve,
        input_reader=input_reader,
        output_writer=output_writer,
        interactive_shell=True,
    )
    agent = runtime.kernel.agent_registry.get("code-assistant")
    if agent is None:
        raise RuntimeError("Missing workspace-local code-assistant agent definition")

    active_session_id = session_id or f"{DEFAULT_SESSION_PREFIX}-{uuid4().hex[:8]}"
    last_terminal_stop_reason: str | None = None
    last_terminal_metadata: dict[str, Any] = {}
    prompt_count = 0
    local_commands: list[str] = []
    workflow_warnings: list[str] = []

    async with runtime.bind_host(host) as bound:
        session = bound.create_session(
            session_id=active_session_id,
            agent_name="code-assistant",
            cwd=workspace_root,
        )
        await _prepare_session(session)
        host.activate_session(active_session_id)
        output_writer("code assistant shell")
        output_writer(f"session: {active_session_id}")
        output_writer(f"workspace: {_display_path(workspace_root)}")
        output_writer("type /help for local commands")
        unsubscribe_jobs, unsubscribe_tasks = await _attach_reactive_watchers(
            bound=bound,
            host=host,
            session_id=active_session_id,
        )
        workflow_ledger = await _workflow_ledger_for_session(
            runtime=runtime,
            session_id=active_session_id,
            live_messages=tuple(session.messages),
        )
        host.render_workflow_state(
            session_id=active_session_id,
            ledger=workflow_ledger.to_payload(),
            force=True,
        )

        while True:
            prompt_boundary = _shell_prompt(active_session_id)
            host.begin_input_wait(prompt_boundary)
            try:
                raw = await asyncio.to_thread(
                    input_reader,
                    prompt_boundary,
                )
            except EOFError:
                host.end_input_wait()
                output_writer("shell closed on EOF")
                break
            except KeyboardInterrupt:
                host.end_input_wait()
                output_writer("shell interrupted")
                break
            host.end_input_wait()

            text = raw.strip()
            if not text:
                continue

            command = _parse_shell_command(text)
            if command is not None:
                local_commands.append(command.name)
                outcome = await _handle_local_command(
                    command=command,
                    bound=bound,
                    layout=resolved_layout,
                    session_id=active_session_id,
                    session=session,
                    output_writer=output_writer,
                )
                if outcome.resume_session_id is not None:
                    unsubscribe_jobs()
                    unsubscribe_tasks()
                    await session.close(
                        final_status=_final_status(last_terminal_metadata, last_terminal_stop_reason)
                    )
                    await _wait_for_background_memory(runtime=runtime, session=session)
                    active_session_id = outcome.resume_session_id
                    session = bound.create_session(
                        session_id=active_session_id,
                        agent_name="code-assistant",
                        cwd=workspace_root,
                    )
                    await _prepare_session(session)
                    host.activate_session(active_session_id)
                    output_writer(f"reattached session: {active_session_id}")
                    unsubscribe_jobs, unsubscribe_tasks = await _attach_reactive_watchers(
                        bound=bound,
                        host=host,
                        session_id=active_session_id,
                    )
                    workflow_ledger = await _workflow_ledger_for_session(
                        runtime=runtime,
                        session_id=active_session_id,
                        live_messages=tuple(session.messages),
                    )
                    host.render_workflow_state(
                        session_id=active_session_id,
                        ledger=workflow_ledger.to_payload(),
                        force=True,
                    )
                    continue
                if outcome.dispatch_prompt is not None:
                    prompt_count += 1
                    prompt_outcome = await _run_session_prompt(
                        session=session,
                        prompt=outcome.dispatch_prompt,
                    )
                    last_terminal_stop_reason = prompt_outcome.terminal_stop_reason
                    last_terminal_metadata = prompt_outcome.terminal_metadata
                    workflow_ledger = await _workflow_ledger_for_session(
                        runtime=runtime,
                        session_id=active_session_id,
                        live_messages=tuple(session.messages),
                    )
                    turn_warnings = _workflow_warnings_for_turn(
                        prompt=outcome.dispatch_prompt,
                        assistant_text=_last_assistant_text(list(prompt_outcome.messages)),
                        ledger=workflow_ledger,
                    )
                    workflow_warnings.extend(turn_warnings)
                    host.render_workflow_state(
                        session_id=active_session_id,
                        ledger=workflow_ledger.to_payload(),
                        warning=turn_warnings[0] if turn_warnings else None,
                    )
                    continue
                if outcome.exit_shell:
                    workflow_ledger = await _workflow_ledger_for_session(
                        runtime=runtime,
                        session_id=active_session_id,
                        live_messages=tuple(session.messages),
                    )
                    warning = _workflow_exit_warning(workflow_ledger)
                    if warning is not None:
                        workflow_warnings.append(warning)
                    host.render_workflow_state(
                        session_id=active_session_id,
                        ledger=workflow_ledger.to_payload(),
                        warning=warning,
                    )
                    break
                continue

            prompt_count += 1
            prompt_outcome = await _run_session_prompt(session=session, prompt=text)
            last_terminal_stop_reason = prompt_outcome.terminal_stop_reason
            last_terminal_metadata = prompt_outcome.terminal_metadata
            workflow_ledger = await _workflow_ledger_for_session(
                runtime=runtime,
                session_id=active_session_id,
                live_messages=tuple(session.messages),
            )
            turn_warnings = _workflow_warnings_for_turn(
                prompt=text,
                assistant_text=_last_assistant_text(list(prompt_outcome.messages)),
                ledger=workflow_ledger,
            )
            workflow_warnings.extend(turn_warnings)
            host.render_workflow_state(
                session_id=active_session_id,
                ledger=workflow_ledger.to_payload(),
                warning=turn_warnings[0] if turn_warnings else None,
            )

        unsubscribe_jobs()
        unsubscribe_tasks()
        await session.close(
            final_status=_final_status(last_terminal_metadata, last_terminal_stop_reason)
        )
        await _wait_for_background_memory(runtime=runtime, session=session)

    memory_context = _memory_context(runtime=runtime, agent=agent, session_id=active_session_id, cwd=workspace_root)
    transcript_path = workspace_root / ".weavert" / "transcripts" / f"{active_session_id}.jsonl"
    child_run_index_path = workspace_root / ".weavert" / "child_runs" / "sessions" / f"{active_session_id}.json"
    error_message = _terminal_error_message(last_terminal_metadata)
    workflow_ledger = await _workflow_ledger_for_session(
        runtime=runtime,
        session_id=active_session_id,
    )
    return ShellReport(
        session_id=active_session_id,
        workspace_root=workspace_root,
        fixture_root=resolved_layout.fixture_root,
        distribution=runtime.kernel.distribution,
        default_model_route=runtime.kernel.config.default_model_route,
        persistence_profile=runtime.query_persistence_profile(),
        transcript_path=transcript_path,
        child_run_index_path=child_run_index_path,
        memory_root=memory_context.memory_root,
        approvals=tuple(approval for approval in host.approvals if approval.session_id == active_session_id),
        child_runs=tuple(_session_child_runs(host.child_run_events, session_id=active_session_id)),
        notification_texts=tuple(message.text for message in host.notifications if message.text),
        prompt_count=prompt_count,
        local_commands=tuple(local_commands),
        job_watch_events=tuple(host.job_watch_events),
        task_watch_events=tuple(host.task_watch_events),
        workflow_events=tuple(host.workflow_events),
        terminal_stop_reason=last_terminal_stop_reason,
        terminal_metadata=last_terminal_metadata,
        workflow_ledger=workflow_ledger,
        workflow_warnings=tuple(_dedupe_preserve_order(workflow_warnings)),
        ok=error_message is None,
        error_message=error_message,
    )


def inspect_demo(*, layout: CodeAssistantLayout | None = None) -> InspectReport:
    return asyncio.run(_inspect_demo_async(layout=layout))


async def _inspect_demo_async(*, layout: CodeAssistantLayout | None = None) -> InspectReport:
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
            changed_files=(),
            workflow_ledger=None,
            memory_root=None,
            memory_documents=0,
        )

    runtime = assemble_demo_runtime(layout=resolved_layout)
    return await _inspect_runtime_state(
        runtime=runtime,
        workspace_root=workspace_root,
        fixture_root=resolved_layout.fixture_root,
        state_root=resolved_layout.state_root,
    )


async def _inspect_runtime_state(
    *,
    runtime,
    workspace_root: Path,
    fixture_root: Path,
    state_root: Path,
    current_session_id: str | None = None,
    current_session: Any = None,
    bound: Any = None,
) -> InspectReport:
    agent = runtime.kernel.agent_registry.get("code-assistant")
    transcript_sessions = _transcript_sessions(workspace_root)
    child_run_records = await _child_run_records(runtime=runtime, session_ids=_session_ids(workspace_root))
    child_run_sessions = _summarize_child_run_sessions(child_run_records)
    task_lists = list(await runtime.list_task_lists())
    changed_files = tuple(_changed_files(workspace_root=workspace_root, fixture_root=fixture_root))
    memory_root = None
    memory_documents = 0
    if agent is not None:
        memory_context = _memory_context(
            runtime=runtime,
            agent=agent,
            session_id=current_session_id
            or (transcript_sessions[0]["session_id"] if transcript_sessions else "inspect-preview"),
            cwd=workspace_root,
        )
        memory_root = memory_context.memory_root
        if memory_root.exists():
            memory_documents = sum(1 for path in memory_root.rglob("*.md") if path.is_file())

    highlighted_task_list_id: str | None = None
    workflow_ledger: WorkflowLedger | None = None
    if current_session_id is not None:
        live_session = current_session
        if live_session is None and hasattr(runtime, "services") and hasattr(runtime.services, "sessions"):
            sessions = runtime.services.sessions
            if hasattr(sessions, "get"):
                live_session = sessions.get(current_session_id)
        transcript_sessions = _merge_current_transcript_session(
            transcript_sessions=transcript_sessions,
            workspace_root=workspace_root,
            session_id=current_session_id,
            session=live_session,
        )
        current_task_list = await _load_current_task_list(
            runtime=runtime,
            bound=bound,
            session_id=current_session_id,
        )
        if current_task_list is not None:
            highlighted_task_list_id = _task_list_identifier(current_task_list)
            task_lists = _merge_current_task_list(task_lists=task_lists, current_task_list=current_task_list)
        workflow_ledger = await _workflow_ledger_for_session(
            runtime=runtime,
            session_id=current_session_id,
            live_messages=tuple(live_session.messages) if live_session is not None and hasattr(live_session, "messages") else None,
        )
    elif transcript_sessions:
        workflow_ledger = await _workflow_ledger_for_session(
            runtime=runtime,
            session_id=str(transcript_sessions[0]["session_id"]),
        )

    return InspectReport(
        workspace_exists=True,
        workspace_root=workspace_root,
        fixture_root=fixture_root,
        state_root=state_root,
        distribution=runtime.kernel.distribution,
        default_model_route=runtime.kernel.config.default_model_route,
        persistence_profile=runtime.query_persistence_profile(),
        transcript_sessions=tuple(transcript_sessions),
        child_run_sessions=tuple(child_run_sessions),
        child_run_records=tuple(child_run_records),
        task_lists=tuple(task_lists),
        changed_files=changed_files,
        workflow_ledger=workflow_ledger,
        memory_root=memory_root,
        memory_documents=memory_documents,
        highlighted_session_id=current_session_id,
        highlighted_task_list_id=highlighted_task_list_id,
    )


async def _prepare_session(session) -> None:
    await session.resume()
    await session.start()


async def _run_session_prompt(*, session, prompt: str) -> PromptOutcome:
    messages: list[RuntimeMessage] = []
    terminal_stop_reason: str | None = None
    terminal_metadata: dict[str, Any] = {}
    turn_id: str | None = None
    session.enqueue_event(InboundEvent(InboundEventType.USER_PROMPT, prompt))
    async for event in session.stream_until_idle():
        if turn_id is None:
            request = event.request
            if request is not None:
                turn_id = request.turn_context.turn_id
            else:
                turn_id = getattr(getattr(session, "state", None), "active_turn_id", None)
        if event.event_type == TurnStreamEventType.MESSAGE and event.message is not None:
            messages.append(event.message)
        elif event.event_type == TurnStreamEventType.TERMINAL and event.terminal is not None:
            terminal_stop_reason = event.terminal.stop_reason
            terminal_metadata = dict(event.terminal.metadata)
    return PromptOutcome(
        messages=tuple(messages),
        terminal_stop_reason=terminal_stop_reason,
        terminal_metadata=terminal_metadata,
        turn_id=turn_id,
    )


async def _attach_reactive_watchers(*, bound, host: CodeAssistantHost, session_id: str):
    unsubscribe_jobs = await bound.watch_jobs(
        session_id=session_id,
        callback=lambda jobs: host.render_job_watch_update(session_id=session_id, jobs=jobs),
    )
    unsubscribe_tasks = await bound.watch_task_list(
        session_id=session_id,
        include_archived=True,
        callback=lambda task_list: host.render_task_watch_update(session_id=session_id, task_list=task_list),
    )
    return unsubscribe_jobs, unsubscribe_tasks


async def _workflow_phase_prompt(
    *,
    phase: str,
    bound,
    layout: CodeAssistantLayout,
    session_id: str,
    focus: str | None,
) -> str:
    task_list = await bound.get_task_list(session_id=session_id, include_archived=True)
    jobs = await bound.list_jobs(session_id=session_id)
    changed_files = _changed_files(workspace_root=layout.workspace_root, fixture_root=layout.fixture_root)
    focus_text = f"\nFocus: {focus}" if focus else ""
    task_lines = _task_context_lines(task_list)
    shell_lines = _latest_shell_outcome_lines(jobs)
    changed_lines = [f"- {path}" for path in changed_files[:10]] or ["- no workspace changes detected"]
    if phase == "review":
        return (
            "Run the standardized review phase for the current workspace. Prefer the `review-change` skill "
            "or ask the `reviewer` agent directly.\n"
            "Use this context when you delegate:\n"
            "Tasks:\n"
            f"{chr(10).join(task_lines)}\n"
            "Changed files:\n"
            f"{chr(10).join(changed_lines)}\n"
            "Latest shell/job outcomes:\n"
            f"{chr(10).join(shell_lines)}\n"
            "Require a final reviewer summary that starts with `review: pass` or `review: fail`."
            f"{focus_text}"
        )
    return (
        "Run the standardized verification phase for the current workspace. Prefer the `verify-change` skill "
        "or ask the `verifier` agent directly.\n"
        "Use this context when you delegate:\n"
        "Tasks:\n"
        f"{chr(10).join(task_lines)}\n"
        "Changed files:\n"
        f"{chr(10).join(changed_lines)}\n"
        "Latest shell/job outcomes:\n"
        f"{chr(10).join(shell_lines)}\n"
        "Require a final verifier summary that starts with `verification: pass` or `verification: fail`."
        f"{focus_text}"
    )


async def _workflow_ledger_for_session(
    *,
    runtime,
    session_id: str,
    live_messages: tuple[RuntimeMessage, ...] | None = None,
) -> WorkflowLedger:
    messages = live_messages
    if messages is None:
        transcript = await runtime.kernel.transcript_store.load(session_id)
        messages = tuple(entry.message for entry in transcript.entries)
    jobs = await runtime.list_jobs(session_id=session_id)
    return _build_workflow_ledger(messages=messages, jobs=jobs)


def _build_workflow_ledger(
    *,
    messages: tuple[RuntimeMessage, ...] | list[RuntimeMessage],
    jobs: tuple[dict[str, Any], ...] | list[dict[str, Any]],
) -> WorkflowLedger:
    change_revision = 0
    verified_revision = 0
    reviewed_revision = 0
    revision_times: list[datetime] = []
    last_verification_outcome: str | None = None
    last_review_outcome: str | None = None

    for message in messages:
        for entry, content in _tool_result_pairs(message):
            tool_name = str(entry.get("tool_name") or "").strip()
            status = str(entry.get("status") or "").strip()
            if (
                tool_name in {"edit", "write"}
                and status == "success"
                and _tool_result_materially_changed(tool_name=tool_name, content=content)
            ):
                change_revision += 1
                revision_times.append(message.created_at)
                continue
            if tool_name == "bash" and _is_verification_shell_result(content):
                outcome = "passed" if status == "success" and _shell_result_passed(content) else "failed"
                last_verification_outcome = outcome
                if outcome == "passed":
                    verified_revision = max(verified_revision, change_revision)
                continue
            if tool_name != "agent":
                continue
            agent_name = str(content.get("agent") or "").strip()
            summary = str(content.get("summary") or "").strip()
            if agent_name == "verifier":
                outcome = _phase_outcome_from_summary(summary=summary, phase="verification")
                last_verification_outcome = outcome
                if outcome == "passed":
                    verified_revision = max(verified_revision, change_revision)
            elif agent_name == "reviewer":
                outcome = _phase_outcome_from_summary(summary=summary, phase="review")
                last_review_outcome = outcome
                if outcome == "passed":
                    reviewed_revision = max(reviewed_revision, change_revision)

    for job in sorted(jobs, key=_job_terminal_sort_key):
        if not isinstance(job, dict):
            continue
        result = job.get("result")
        timestamps = job.get("timestamps")
        if not isinstance(result, dict) or not isinstance(timestamps, dict):
            continue
        if not _is_verification_shell_result(result):
            continue
        ended_at = _coerce_datetime(timestamps.get("ended_at")) or _coerce_datetime(timestamps.get("updated_at"))
        if ended_at is None:
            continue
        covered_revision = _covered_revision_at(revision_times, ended_at)
        if covered_revision < 1:
            continue
        status = str(job.get("status") or "").strip()
        outcome = "passed" if status == "completed" and _shell_result_passed(result) else "failed"
        last_verification_outcome = outcome
        if outcome == "passed":
            verified_revision = max(verified_revision, covered_revision)

    current_state = _workflow_state_from_revisions(
        change_revision=change_revision,
        verified_revision=verified_revision,
        reviewed_revision=reviewed_revision,
    )
    return WorkflowLedger(
        change_revision=change_revision,
        verified_revision=verified_revision,
        reviewed_revision=reviewed_revision,
        current_state=current_state,
        last_verification_outcome=last_verification_outcome,
        last_review_outcome=last_review_outcome,
    )


def _workflow_state_from_revisions(
    *,
    change_revision: int,
    verified_revision: int,
    reviewed_revision: int,
) -> str:
    if change_revision == 0:
        return "clean"
    if verified_revision < change_revision:
        return "pending_verification"
    if reviewed_revision < change_revision:
        return "pending_review"
    return "ready_to_summarize"


def _workflow_warnings_for_state(
    ledger: WorkflowLedger,
    *,
    include_summary_warning: bool,
    summary_label: str = "Final summary",
) -> tuple[str, ...]:
    if not include_summary_warning:
        return ()
    if ledger.current_state not in {"pending_verification", "pending_review"}:
        return ()
    return (
        f"{summary_label} was produced while the workflow was still {ledger.current_state}.",
    )


def _workflow_warnings_for_turn(
    *,
    prompt: str,
    assistant_text: str,
    ledger: WorkflowLedger,
) -> tuple[str, ...]:
    prompt_warning = _workflow_warning_for_user_prompt(prompt, ledger)
    if prompt_warning is not None:
        return (prompt_warning,)
    return _workflow_warnings_for_state(
        ledger,
        include_summary_warning=bool(assistant_text),
        summary_label="Assistant response",
    )


def _workflow_warning_for_user_prompt(prompt: str, ledger: WorkflowLedger) -> str | None:
    if ledger.current_state not in {"pending_verification", "pending_review"}:
        return None
    lowered = prompt.lower()
    if any(marker in lowered for marker in ("summary", "summarize", "done", "finish", "final", "complete", "exit", "quit")):
        return (
            f"The latest workspace is still {ledger.current_state}; "
            "summary or exit remains advisory only."
        )
    return None


def _workflow_exit_warning(ledger: WorkflowLedger) -> str | None:
    if ledger.current_state not in {"pending_verification", "pending_review"}:
        return None
    return f"Exiting while the workflow is still {ledger.current_state}."


def _tool_result_pairs(message: RuntimeMessage) -> tuple[tuple[dict[str, Any], dict[str, Any]], ...]:
    if message.role != MessageRole.USER:
        return ()
    raw_entries = message.metadata.get("tool_results")
    if not isinstance(raw_entries, list):
        return ()
    entries_by_id = {
        str(entry.get("tool_use_id") or ""): entry
        for entry in raw_entries
        if isinstance(entry, dict)
    }
    pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for block in message.content:
        if not isinstance(block, ToolResultBlock) or not isinstance(block.content, dict):
            continue
        entry = entries_by_id.get(block.tool_use_id)
        if entry is None:
            continue
        pairs.append((entry, block.content))
    return tuple(pairs)


def _tool_result_materially_changed(*, tool_name: str, content: dict[str, Any]) -> bool:
    if tool_name == "edit":
        return bool(content.get("updated", True))
    if tool_name == "write":
        return bool(content.get("changed", True))
    return False


def _is_verification_shell_result(content: dict[str, Any]) -> bool:
    classification = str(content.get("classification") or "").strip()
    if classification in {"test", "build"}:
        return True
    command = str(content.get("command") or "").lower()
    description = str(content.get("description") or "").lower()
    return any(
        marker in command or marker in description
        for marker in ("pytest", "unittest", " test", " check", "verification")
    )


def _shell_result_passed(content: dict[str, Any]) -> bool:
    shell_status = str(content.get("status") or "").strip()
    exit_code = content.get("exit_code")
    return shell_status == "completed" and (exit_code is None or exit_code == 0)


def _phase_outcome_from_summary(*, summary: str, phase: str) -> str:
    lowered = summary.lower().strip()
    if lowered.startswith(f"{phase}: fail"):
        return "failed"
    if lowered.startswith(f"{phase}: pass"):
        return "passed"
    if " fail" in lowered or lowered.startswith("fail"):
        return "failed"
    if "passed" in lowered or "no issues" in lowered or "pass" in lowered:
        return "passed"
    return "failed"


def _covered_revision_at(revision_times: list[datetime], event_time: datetime) -> int:
    covered = 0
    for revision_time in revision_times:
        if revision_time <= event_time:
            covered += 1
    return covered


def _job_terminal_sort_key(job: dict[str, Any]) -> tuple[datetime, str]:
    timestamps = job.get("timestamps") if isinstance(job.get("timestamps"), dict) else {}
    ended_at = _coerce_datetime(timestamps.get("ended_at"))
    updated_at = _coerce_datetime(timestamps.get("updated_at"))
    return (ended_at or updated_at or datetime.min, str(job.get("job_id") or ""))


def _coerce_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _changed_files(*, workspace_root: Path, fixture_root: Path) -> list[str]:
    workspace_files = {
        str(path.relative_to(workspace_root))
        for path in workspace_root.rglob("*")
        if path.is_file() and ".weavert" not in path.relative_to(workspace_root).parts
    }
    fixture_files = {
        str(path.relative_to(fixture_root))
        for path in fixture_root.rglob("*")
        if path.is_file() and ".weavert" not in path.relative_to(fixture_root).parts
    }
    changed: list[str] = []
    for relative in sorted(workspace_files | fixture_files):
        workspace_path = workspace_root / relative
        fixture_path = fixture_root / relative
        if not workspace_path.exists() or not fixture_path.exists():
            changed.append(relative)
            continue
        if workspace_path.read_bytes() != fixture_path.read_bytes():
            changed.append(relative)
    return changed


def _task_context_lines(task_list: dict[str, Any]) -> list[str]:
    tasks = task_list.get("tasks", ())
    if not isinstance(tasks, list) or not tasks:
        return ["- no shared tasks yet"]
    lines: list[str] = []
    for task in tasks[:8]:
        if not isinstance(task, dict):
            continue
        readiness = str(task.get("readiness_state") or "").strip()
        readiness_suffix = f", {readiness}" if readiness else ""
        lines.append(
            f"- {task.get('subject', '<unnamed>')} "
            f"[{task.get('status', 'unknown')}{readiness_suffix}]"
        )
    return lines or ["- no shared tasks yet"]


def _latest_shell_outcome_lines(jobs: tuple[dict[str, Any], ...] | list[dict[str, Any]]) -> list[str]:
    if not jobs:
        return ["- no visible shell jobs"]
    lines: list[str] = []
    for job in list(jobs)[:6]:
        if not isinstance(job, dict):
            continue
        result = job.get("result") if isinstance(job.get("result"), dict) else {}
        summary = str(result.get("output_summary") or job.get("summary") or "<job>")
        status = str(job.get("status") or "unknown")
        lines.append(f"- {job.get('job_id', '<job>')} [{status}] {summary}")
    return lines or ["- no visible shell jobs"]


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


async def _handle_local_command(
    *,
    command: LocalShellCommand,
    bound,
    layout: CodeAssistantLayout,
    session_id: str,
    session,
    output_writer,
) -> LocalCommandOutcome:
    if command.name == "help":
        _print_shell_help(output_writer=output_writer)
        return LocalCommandOutcome()
    if command.name == "exit":
        output_writer("closing shell")
        return LocalCommandOutcome(exit_shell=True)
    if command.name == "inspect":
        _print_inspect_report(
            await _inspect_runtime_state(
                runtime=bound.runtime,
                workspace_root=layout.workspace_root,
                fixture_root=layout.fixture_root,
                state_root=layout.state_root,
                current_session_id=session_id,
                current_session=session,
                bound=bound,
            ),
            output_writer=output_writer,
            current_session_id=session_id,
        )
        return LocalCommandOutcome()
    if command.name == "resume":
        sessions = _transcript_sessions(layout.workspace_root)
        if not sessions:
            output_writer("no resumable sessions were found")
            return LocalCommandOutcome()
        if command.argument is None:
            output_writer("resumable sessions:")
            for session in sessions[:10]:
                output_writer(
                    f"- {session['session_id']} "
                    f"({_display_path(Path(session['path']))}, {session['entries']} entries)"
                )
            output_writer("use /resume <session-id> or /resume latest to reattach")
            return LocalCommandOutcome()
        target = command.argument.strip()
        if target == "latest":
            target = str(sessions[0]["session_id"])
        if target == session_id:
            output_writer(f"already attached to session: {session_id}")
            return LocalCommandOutcome()
        if target not in {str(item["session_id"]) for item in sessions}:
            output_writer(f"unknown session: {target}")
            return LocalCommandOutcome()
        return LocalCommandOutcome(resume_session_id=target)
    if command.name == "tasks":
        task_list = await bound.get_task_list(session_id=session_id, include_archived=True)
        _print_task_list(task_list=task_list, output_writer=output_writer)
        return LocalCommandOutcome()
    if command.name == "jobs":
        jobs = await bound.list_jobs(session_id=session_id)
        _print_jobs(jobs=jobs, output_writer=output_writer)
        return LocalCommandOutcome()
    if command.name == "review":
        dispatch_prompt = await _workflow_phase_prompt(
            phase="review",
            bound=bound,
            layout=layout,
            session_id=session_id,
            focus=command.argument,
        )
        return LocalCommandOutcome(
            dispatch_prompt=dispatch_prompt
        )
    if command.name == "verify":
        dispatch_prompt = await _workflow_phase_prompt(
            phase="verify",
            bound=bound,
            layout=layout,
            session_id=session_id,
            focus=command.argument,
        )
        return LocalCommandOutcome(
            dispatch_prompt=dispatch_prompt
        )
    output_writer(f"unknown local command: /{command.name}")
    output_writer("type /help for the supported command list")
    return LocalCommandOutcome()


def _parse_shell_command(text: str) -> LocalShellCommand | None:
    if not text.startswith("/"):
        return None
    body = text[1:].strip()
    if not body:
        return LocalShellCommand(name="")
    name, _, argument = body.partition(" ")
    return LocalShellCommand(
        name=name.strip().lower(),
        argument=argument.strip() or None,
    )


def _print_shell_help(*, output_writer) -> None:
    output_writer("local commands:")
    output_writer("- /help: show the local command list")
    output_writer("- /inspect: print runtime, transcript, task, and memory diagnostics")
    output_writer("- /resume [session-id|latest]: list resumable sessions or reattach to one")
    output_writer("- /tasks: inspect the shared task list without spending a model turn")
    output_writer("- /jobs: inspect visible background jobs without spending a model turn")
    output_writer("- /review [focus]: dispatch a review-oriented prompt through the runtime")
    output_writer("- /verify [focus]: dispatch a verification-oriented prompt through the runtime")
    output_writer("- /exit: close the shell cleanly")


def _print_inspect_report(
    report: InspectReport,
    *,
    output_writer,
    current_session_id: str | None = None,
) -> None:
    output_writer("code assistant inspect")
    if current_session_id is not None:
        output_writer(f"current session: {current_session_id}")
    output_writer(f"workspace exists: {'yes' if report.workspace_exists else 'no'}")
    output_writer(f"fixture: {_display_path(report.fixture_root)}")
    output_writer(f"state root: {_display_path(report.state_root)}")
    if not report.workspace_exists:
        return
    output_writer(f"workspace: {_display_path(report.workspace_root)}")
    output_writer(f"distribution: {report.distribution}")
    output_writer(f"default route: {report.default_model_route}")
    output_writer(
        "persistence profile: "
        f"{report.persistence_profile.get('profile_kind', 'unknown')}"
    )
    output_writer(f"transcript sessions: {len(report.transcript_sessions)}")
    highlighted_transcript = _find_transcript_session(
        report.transcript_sessions,
        session_id=report.highlighted_session_id,
    )
    if highlighted_transcript is not None:
        output_writer(_format_transcript_session_line(label="current transcript", session=highlighted_transcript))
    elif report.transcript_sessions:
        output_writer(_format_transcript_session_line(label="latest transcript", session=report.transcript_sessions[0]))
    output_writer(f"child run sessions: {len(report.child_run_sessions)}")
    output_writer(f"task lists: {len(report.task_lists)}")
    if report.highlighted_task_list_id is not None:
        output_writer(f"current task list: {report.highlighted_task_list_id}")
    if report.workflow_ledger is not None:
        output_writer(
            "workflow: "
            f"{report.workflow_ledger.current_state} "
            f"(change={report.workflow_ledger.change_revision}, "
            f"verified={report.workflow_ledger.verified_revision}, "
            f"reviewed={report.workflow_ledger.reviewed_revision})"
        )
    output_writer(f"changed files: {len(report.changed_files)}")
    for file_path in report.changed_files[:10]:
        output_writer(f"- changed {file_path}")
    if report.memory_root is not None:
        output_writer(f"memory root: {_display_path(report.memory_root)}")
        output_writer(f"memory documents: {report.memory_documents}")


def _print_task_list(*, task_list: dict[str, Any], output_writer) -> None:
    tasks = task_list.get("tasks", [])
    task_list_id = task_list.get("list_id") or task_list.get("task_list_id") or "<unknown>"
    output_writer(f"task list: {task_list_id}")
    if not isinstance(tasks, list) or not tasks:
        output_writer("no shared tasks yet")
        return
    for task in tasks:
        if not isinstance(task, dict):
            continue
        readiness = str(task.get("readiness_state") or "").strip()
        readiness_suffix = f", {readiness}" if readiness else ""
        output_writer(
            f"- {task.get('subject', '<unnamed>')} "
            f"[{task.get('status', 'unknown')}{readiness_suffix}]"
        )


def _print_jobs(*, jobs: tuple[dict[str, Any], ...], output_writer) -> None:
    output_writer(f"jobs: {len(jobs)}")
    if not jobs:
        output_writer("no visible background jobs")
        return
    for job in jobs:
        metadata = job.get("metadata") if isinstance(job, dict) else {}
        result = job.get("result") if isinstance(job, dict) else {}
        classification = ""
        kind = ""
        if isinstance(metadata, dict):
            classification = str(metadata.get("classification") or "").strip()
            kind = str(metadata.get("kind") or "").strip()
        summary = str(job.get("summary") or "<job>")
        status = str(job.get("status") or "unknown")
        classification_suffix = f", {classification}" if classification else ""
        output_writer(
            f"- {job.get('job_id', '<job>')} [{status}{classification_suffix}] {summary}"
        )
        if kind in {"background_shell", "shell_session"} and status in {"pending", "running"}:
            command = str(metadata.get("command") or "").strip()
            job_id = str(job.get("job_id") or "").strip()
            job_suffix = f", job={job_id}" if job_id else ""
            shell_session_id = str(metadata.get("shell_session_id") or "").strip()
            session_suffix = f", session={shell_session_id}" if shell_session_id else ""
            output_writer(
                f"[bash:running] {classification}{job_suffix}{session_suffix} {command}".rstrip()
            )
        if isinstance(result, dict) and isinstance(result.get("output_summary"), str):
            output_writer(f"  {result['output_summary']}")


def _shell_prompt(session_id: str) -> str:
    return f"code-assistant[{session_id[:8]}]> "


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(Path.cwd()))
    except ValueError:
        return str(path)


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
        sessions.append(
            {
                "session_id": path.stem,
                "path": path,
                "entries": _count_transcript_entries(path),
            }
        )
    return sessions


def _count_transcript_entries(path: Path) -> int:
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def _merge_current_transcript_session(
    *,
    transcript_sessions: list[dict[str, Any]],
    workspace_root: Path,
    session_id: str,
    session: Any = None,
) -> list[dict[str, Any]]:
    transcript_path = workspace_root / ".weavert" / "transcripts" / f"{session_id}.jsonl"
    live_entries = None
    if session is not None and hasattr(session, "messages"):
        live_entries = len(tuple(session.messages))
    entry = {
        "session_id": session_id,
        "path": transcript_path,
        "entries": live_entries if live_entries is not None else _count_transcript_entries(transcript_path)
        if transcript_path.exists()
        else 0,
        "live": session is not None,
        "persisted": transcript_path.exists(),
    }
    merged = [entry]
    merged.extend(
        item for item in transcript_sessions if str(item.get("session_id") or "") != session_id
    )
    return merged


async def _load_current_task_list(
    *,
    runtime,
    bound,
    session_id: str,
) -> dict[str, Any] | None:
    if bound is not None:
        return await bound.get_task_list(session_id=session_id, include_archived=True)
    return await runtime.get_task_list(session_id=session_id, include_archived=True)


def _task_list_identifier(task_list: dict[str, Any]) -> str | None:
    task_list_id = task_list.get("list_id") or task_list.get("task_list_id")
    if not isinstance(task_list_id, str):
        return None
    value = task_list_id.strip()
    return value or None


def _merge_current_task_list(
    *,
    task_lists: list[dict[str, Any]],
    current_task_list: dict[str, Any],
) -> list[dict[str, Any]]:
    current_task_list_id = _task_list_identifier(current_task_list)
    if current_task_list_id is None:
        return list(task_lists)
    merged = [current_task_list]
    merged.extend(
        item for item in task_lists if _task_list_identifier(item) != current_task_list_id
    )
    return merged


def _find_transcript_session(
    sessions: tuple[dict[str, Any], ...] | list[dict[str, Any]],
    *,
    session_id: str | None,
) -> dict[str, Any] | None:
    if session_id is None:
        return None
    for session in sessions:
        if str(session.get("session_id") or "") == session_id:
            return session
    return None


def _format_transcript_session_line(*, label: str, session: dict[str, Any]) -> str:
    status: list[str] = []
    if session.get("live") is True:
        status.append("live")
    if session.get("persisted") is True:
        status.append("persisted")
    status_suffix = f", {', '.join(status)}" if status else ""
    return (
        f"{label}: {session['session_id']} "
        f"({_display_path(Path(session['path']))}, {session['entries']} entries{status_suffix})"
    )


def _final_status(terminal_metadata: dict[str, Any], terminal_stop_reason: str | None) -> str:
    if terminal_metadata.get("failure_class") not in {None, "", "none"}:
        return "failed"
    if terminal_stop_reason == "interrupted":
        return "interrupted"
    if terminal_stop_reason == "blocked":
        return "stopped"
    return "completed"


def _last_assistant_text(messages: list[RuntimeMessage]) -> str:
    return final_assistant_text(messages)


def _terminal_error_message(terminal_metadata: dict[str, Any]) -> str | None:
    failure_class = str(terminal_metadata.get("failure_class") or "").strip()
    if not failure_class or failure_class == "none":
        return None
    error = str(terminal_metadata.get("error") or failure_class).strip()
    return error or failure_class


def _workflow_validation_result(
    *,
    messages: list[RuntimeMessage],
    approvals: list[ApprovalRecord],
    child_run_records: list[AgentRunRecord],
    task_list: dict[str, Any],
    final_text: str,
    workflow_ledger: WorkflowLedger,
    current_turn_id: str | None = None,
) -> WorkflowValidationResult:
    gaps: list[str] = []
    advisories: list[str] = []
    parent_events = _tool_result_events(messages, scope="parent")
    current_turn_records = _child_run_records_for_parent_turn(
        child_run_records,
        parent_turn_id=current_turn_id,
    )
    planner_records = _child_run_records_for_agent(current_turn_records, agent_name="coding-planner")
    planner_events = _child_tool_result_events(planner_records, scope="planner")
    verifier_records = _child_run_records_for_agent(current_turn_records, agent_name="verifier")
    verifier_events = _child_tool_result_events(verifier_records, scope="verifier")
    planning_outcome = _planning_outcome(planner_records=planner_records, task_list=task_list)
    inspection_outcome = _inspection_outcome(parent_events + planner_events)

    if not _has_successful_tool(parent_events, "skill"):
        gaps.append("the workflow skill did not run")

    skill_result = _find_skill_result(messages, skill_name="coding-loop")
    if skill_result is None:
        gaps.append("the coding-loop skill was not applied")
    elif skill_result.get("mode") != "inline":
        gaps.append("the coding-loop skill did not run inline")

    if not _has_successful_tool(parent_events + planner_events, "task_list"):
        gaps.append("the shared task list was never inspected")

    if planning_outcome.classification == "failed":
        gaps.append(_planning_failure_message(planning_outcome))
    elif planning_outcome.classification == "degraded":
        advisories.append(_planning_advisory_message(planning_outcome))

    if not inspection_outcome.satisfied:
        if inspection_outcome.late_only:
            gaps.append("repository inspection only happened after the first material edit")
        else:
            gaps.append("the workflow never used glob, grep, or read before the first material edit")

    for tool_name in ("edit", "write"):
        if not _has_successful_tool(parent_events, tool_name):
            gaps.append(f"the workflow never used {tool_name}")

    if not _has_successful_verification_shell(parent_events + verifier_events):
        gaps.append("the workflow never used bash verification")

    approval_names = {approval.name for approval in approvals}
    for tool_name in ("edit", "write", "bash"):
        if tool_name not in approval_names:
            gaps.append(f"host approval for {tool_name} was never recorded")

    for agent_name in ("reviewer", "verifier"):
        status = _latest_child_run_status(
            _child_run_records_for_agent(current_turn_records, agent_name=agent_name)
        )
        if status is None:
            gaps.append(f"the {agent_name} child run never executed")
        elif status != "completed":
            gaps.append(f"the {agent_name} child run ended with status '{status}'")

    tasks = task_list.get("tasks", ())
    if not isinstance(tasks, list) or not tasks:
        gaps.append("the shared task list is empty")

    if workflow_ledger.change_revision > 0 and workflow_ledger.verified_revision < workflow_ledger.change_revision:
        gaps.append("the latest revision is not covered by verification")
    if workflow_ledger.change_revision > 0 and workflow_ledger.reviewed_revision < workflow_ledger.change_revision:
        gaps.append("the latest revision is not covered by review")

    if not final_text.strip():
        gaps.append("the assistant did not return a final summary")

    return WorkflowValidationResult(
        workflow_gaps=tuple(gaps),
        workflow_advisories=tuple(advisories),
    )


def _project_child_runs(
    child_run_records: tuple[AgentRunRecord, ...] | list[AgentRunRecord],
    *,
    session_id: str,
) -> tuple[dict[str, Any], ...]:
    projected: list[dict[str, Any]] = []
    for record in child_run_records:
        projection = project_child_run_record(record)
        projection["session_id"] = session_id
        projected.append(projection)
    return tuple(projected)


def _tool_result_events(
    messages: tuple[RuntimeMessage, ...] | list[RuntimeMessage],
    *,
    scope: str,
    agent_name: str | None = None,
    run_id: str | None = None,
) -> list[ToolResultEvent]:
    events: list[ToolResultEvent] = []
    for message_index, message in enumerate(messages):
        for result_index, (entry, content) in enumerate(_tool_result_pairs(message)):
            status = str(entry.get("status") or "").strip()
            tool_name = str(entry.get("tool_name") or "").strip()
            if not status or not tool_name:
                continue
            payload = content if isinstance(content, dict) else {}
            events.append(
                ToolResultEvent(
                    scope=scope,
                    agent_name=agent_name,
                    run_id=run_id,
                    tool_name=tool_name,
                    status=status,
                    created_at=message.created_at,
                    message_index=message_index,
                    result_index=result_index,
                    content=payload,
                )
            )
    return events


def _child_tool_result_events(
    records: tuple[AgentRunRecord, ...] | list[AgentRunRecord],
    *,
    scope: str,
) -> list[ToolResultEvent]:
    events: list[ToolResultEvent] = []
    for record in records:
        events.extend(
            _tool_result_events(
                record.messages,
                scope=scope,
                agent_name=record.agent_name,
                run_id=record.run_id,
            )
        )
    return events


def _child_run_records_for_agent(
    child_run_records: tuple[AgentRunRecord, ...] | list[AgentRunRecord],
    *,
    agent_name: str,
) -> list[AgentRunRecord]:
    return [record for record in child_run_records if record.agent_name == agent_name]


def _child_run_records_for_parent_turn(
    child_run_records: tuple[AgentRunRecord, ...] | list[AgentRunRecord],
    *,
    parent_turn_id: str | None,
) -> list[AgentRunRecord]:
    if not parent_turn_id:
        return list(child_run_records)
    return [record for record in child_run_records if record.parent_turn_id == parent_turn_id]


def _latest_child_run_status(records: tuple[AgentRunRecord, ...] | list[AgentRunRecord]) -> str | None:
    projection = child_summary(records)
    return projection.status if projection is not None else None


def _planning_outcome(
    *,
    planner_records: tuple[AgentRunRecord, ...] | list[AgentRunRecord],
    task_list: dict[str, Any],
) -> PlanningOutcome:
    if not planner_records:
        return PlanningOutcome(
            classification="failed",
            terminal_status=None,
            summary=None,
            visible_task_ids=(),
        )
    visible_task_ids = _visible_task_ids(task_list)
    best = PlanningOutcome(classification="failed", terminal_status=None, summary=None, visible_task_ids=())
    best_rank = -1
    for record in planner_records:
        planner_task_ids = _planner_visible_task_ids(record, visible_task_ids=visible_task_ids)
        summary = _last_assistant_text(list(record.messages)).strip() or None
        if record.status.value == "completed" and summary and planner_task_ids:
            classification = "completed"
        elif record.status.value != "completed" and planner_task_ids:
            classification = "degraded"
        else:
            classification = "failed"
        outcome = PlanningOutcome(
            classification=classification,
            terminal_status=record.status.value,
            summary=summary,
            visible_task_ids=planner_task_ids,
        )
        rank = {"failed": 0, "degraded": 1, "completed": 2}[classification]
        if rank >= best_rank:
            best = outcome
            best_rank = rank
    return best


def _planning_failure_message(outcome: PlanningOutcome) -> str:
    if outcome.terminal_status is None:
        return "the coding-planner child run never executed"
    if outcome.terminal_status == "completed":
        return "the planning phase did not leave a planner-authored shared plan outcome"
    return (
        "the coding-planner child run ended with status "
        f"'{outcome.terminal_status}' without leaving a planner-authored shared plan outcome"
    )


def _planning_advisory_message(outcome: PlanningOutcome) -> str:
    task_label = "task" if len(outcome.visible_task_ids) == 1 else "tasks"
    return (
        "planner degraded: the coding-planner child run ended with status "
        f"'{outcome.terminal_status}' after leaving {len(outcome.visible_task_ids)} visible shared {task_label}"
    )


def _visible_task_ids(task_list: dict[str, Any]) -> set[str]:
    tasks = task_list.get("tasks", ())
    if not isinstance(tasks, list):
        return set()
    task_ids: set[str] = set()
    for task in tasks:
        if not isinstance(task, dict):
            continue
        task_id = str(task.get("task_id") or "").strip()
        if task_id:
            task_ids.add(task_id)
    return task_ids


def _planner_visible_task_ids(
    record: AgentRunRecord,
    *,
    visible_task_ids: set[str],
) -> tuple[str, ...]:
    task_ids: list[str] = []
    seen: set[str] = set()
    for event in _tool_result_events(
        record.messages,
        scope="planner",
        agent_name=record.agent_name,
        run_id=record.run_id,
    ):
        if event.status != "success" or not _is_planner_task_mutation(event.tool_name):
            continue
        task_id = _task_id_from_content(event.content)
        if task_id is None or task_id in seen or task_id not in visible_task_ids:
            continue
        seen.add(task_id)
        task_ids.append(task_id)
    return tuple(task_ids)


def _is_planner_task_mutation(tool_name: str) -> bool:
    return tool_name in {
        "task_assign_next",
        "task_block",
        "task_claim",
        "task_create",
        "task_release",
        "task_unarchive",
        "task_unblock",
        "task_update",
    }


def _task_id_from_content(content: dict[str, Any]) -> str | None:
    task = content.get("task")
    if not isinstance(task, dict):
        return None
    task_id = str(task.get("task_id") or "").strip()
    return task_id or None


def _inspection_outcome(events: tuple[ToolResultEvent, ...] | list[ToolResultEvent]) -> InspectionOutcome:
    ordered_events = sorted(events, key=_tool_result_event_order_key)
    first_edit_key = _first_material_edit_key(ordered_events)
    late_only = False
    for event in ordered_events:
        if event.status != "success" or event.tool_name not in {"glob", "grep", "read"}:
            continue
        if first_edit_key is None or _tool_result_event_order_key(event) < first_edit_key:
            return InspectionOutcome(satisfied=True)
        late_only = True
    return InspectionOutcome(satisfied=False, late_only=late_only)


def _first_material_edit_key(
    events: tuple[ToolResultEvent, ...] | list[ToolResultEvent],
) -> tuple[datetime, int, int] | None:
    material_keys = [
        _tool_result_event_order_key(event)
        for event in events
        if event.status == "success"
        and event.tool_name in {"edit", "write"}
        and _tool_result_materially_changed(tool_name=event.tool_name, content=event.content)
    ]
    if not material_keys:
        return None
    return min(material_keys)


def _tool_result_event_order_key(event: ToolResultEvent) -> tuple[datetime, int, int]:
    return (
        event.created_at,
        event.message_index,
        event.result_index,
    )


def _has_successful_tool(
    events: tuple[ToolResultEvent, ...] | list[ToolResultEvent],
    tool_name: str,
) -> bool:
    return any(event.status == "success" and event.tool_name == tool_name for event in events)


def _has_successful_verification_shell(
    events: tuple[ToolResultEvent, ...] | list[ToolResultEvent],
) -> bool:
    for event in events:
        if event.status != "success" or event.tool_name != "bash":
            continue
        if _is_verification_shell_result(event.content):
            return True
    return False


def _find_skill_result(messages: list[RuntimeMessage], *, skill_name: str) -> dict[str, Any] | None:
    projection = latest_skill_outcome(messages, skill_name=skill_name)
    if projection is None:
        return None
    return dict(projection.payload)


def _workflow_error_message(workflow_gaps: tuple[str, ...]) -> str | None:
    if not workflow_gaps:
        return None
    return "Workflow validation failed: " + "; ".join(workflow_gaps)


def _session_child_runs(records: list[dict[str, Any]], *, session_id: str) -> list[dict[str, Any]]:
    return [record for record in records if str(record.get("session_id") or "") == session_id]


__all__ = [
    "CODE_ASSISTANT_STATE_ROOT_ENV",
    "CodeAssistantLayout",
    "DEFAULT_PROMPT",
    "InspectReport",
    "RunReport",
    "ShellReport",
    "assemble_demo_runtime",
    "default_layout",
    "ensure_demo_state",
    "inspect_demo",
    "reset_demo_state",
    "run_demo",
    "shell_demo",
]
