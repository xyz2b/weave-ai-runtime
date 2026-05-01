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
from weavert.runtime_kernel import (
    BuiltinPackConfig,
    DefinitionSourcePaths,
    RuntimeConfig,
    RuntimeDistribution,
    assemble_runtime,
)
from weavert.session_runtime import InboundEvent, InboundEventType
from weavert.turn_engine.engine import TurnStreamEventType

from .builtin_overrides import (
    build_code_assistant_bash_replacement,
    reconcile_background_shell_jobs,
)
from .host import ApprovalRecord, CodeAssistantHost

DEFAULT_SESSION_PREFIX = "code-assistant"
DEFAULT_PROMPT = """Work in the current mini repo.

Goal:
1. Apply the `coding-loop` skill at the start of the task.
2. Ask the `coding-planner` agent to turn the goal into a short shared task plan.
3. Make the greeting tests pass by updating the default greeting to "Hello, WeaveRT.".
4. Add a new file at notes/live_demo.md with one short sentence describing the change.
5. Run `python3 -m unittest discover -s tests`.
6. Ask the `reviewer` agent to review the final workspace.
7. Ask the `verifier` agent to confirm the verification result.

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
    terminal_stop_reason: str | None
    terminal_metadata: dict[str, Any]
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


@dataclass(frozen=True, slots=True)
class PromptOutcome:
    messages: tuple[RuntimeMessage, ...]
    terminal_stop_reason: str | None
    terminal_metadata: dict[str, Any]


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
        builtins=BuiltinPackConfig(
            tool_replacements={"bash": build_code_assistant_bash_replacement()},
        ),
        model_client=model_client,
    )
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

    memory_context = _memory_context(runtime=runtime, agent=agent, session_id=resolved_session_id, cwd=workspace_root)
    transcript_path = workspace_root / ".weavert" / "transcripts" / f"{resolved_session_id}.jsonl"
    child_run_index_path = workspace_root / ".weavert" / "child_runs" / "sessions" / f"{resolved_session_id}.json"
    final_text = _last_assistant_text(list(outcome.messages))
    error_message = _terminal_error_message(outcome.terminal_metadata)
    workflow_gaps: tuple[str, ...] = ()
    if error_message is None and validate_workflow:
        workflow_gaps = _workflow_validation_gaps(
            messages=list(outcome.messages),
            approvals=[approval for approval in host.approvals if approval.session_id == resolved_session_id],
            child_runs=_session_child_runs(host.child_run_events, session_id=resolved_session_id),
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
        messages=outcome.messages,
        final_text=final_text,
        approvals=tuple(host.approvals),
        child_runs=tuple(_session_child_runs(host.child_run_events, session_id=resolved_session_id)),
        task_list_id=task_list_id,
        task_list=task_list,
        transcript_path=transcript_path,
        child_run_index_path=child_run_index_path,
        memory_root=memory_context.memory_root,
        notification_texts=tuple(message.text for message in host.notifications if message.text),
        terminal_stop_reason=outcome.terminal_stop_reason,
        terminal_metadata=outcome.terminal_metadata,
        workflow_gaps=workflow_gaps,
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

    async with runtime.bind_host(host) as bound:
        session = bound.create_session(
            session_id=active_session_id,
            agent_name="code-assistant",
            cwd=workspace_root,
        )
        await _prepare_session(session)
        output_writer("code assistant shell")
        output_writer(f"session: {active_session_id}")
        output_writer(f"workspace: {_display_path(workspace_root)}")
        output_writer("type /help for local commands")

        while True:
            try:
                raw = await asyncio.to_thread(
                    input_reader,
                    _shell_prompt(active_session_id),
                )
            except EOFError:
                output_writer("shell closed on EOF")
                break
            except KeyboardInterrupt:
                output_writer("shell interrupted")
                break

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
                    output_writer=output_writer,
                )
                if outcome.resume_session_id is not None:
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
                    output_writer(f"reattached session: {active_session_id}")
                    continue
                if outcome.dispatch_prompt is not None:
                    prompt_count += 1
                    prompt_outcome = await _run_session_prompt(
                        session=session,
                        prompt=outcome.dispatch_prompt,
                    )
                    last_terminal_stop_reason = prompt_outcome.terminal_stop_reason
                    last_terminal_metadata = prompt_outcome.terminal_metadata
                    continue
                if outcome.exit_shell:
                    break
                continue

            prompt_count += 1
            prompt_outcome = await _run_session_prompt(session=session, prompt=text)
            last_terminal_stop_reason = prompt_outcome.terminal_stop_reason
            last_terminal_metadata = prompt_outcome.terminal_metadata

        await session.close(
            final_status=_final_status(last_terminal_metadata, last_terminal_stop_reason)
        )
        await _wait_for_background_memory(runtime=runtime, session=session)

    memory_context = _memory_context(runtime=runtime, agent=agent, session_id=active_session_id, cwd=workspace_root)
    transcript_path = workspace_root / ".weavert" / "transcripts" / f"{active_session_id}.jsonl"
    child_run_index_path = workspace_root / ".weavert" / "child_runs" / "sessions" / f"{active_session_id}.json"
    error_message = _terminal_error_message(last_terminal_metadata)
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
        terminal_stop_reason=last_terminal_stop_reason,
        terminal_metadata=last_terminal_metadata,
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
            memory_root=None,
            memory_documents=0,
        )

    runtime = assemble_demo_runtime(layout=resolved_layout)
    agent = runtime.kernel.agent_registry.get("code-assistant")
    transcript_sessions = _transcript_sessions(workspace_root)
    child_run_records = await _child_run_records(runtime=runtime, session_ids=_session_ids(workspace_root))
    child_run_sessions = _summarize_child_run_sessions(child_run_records)
    task_lists = await runtime.list_task_lists()
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


async def _prepare_session(session) -> None:
    await session.resume()
    await session.start()


async def _run_session_prompt(*, session, prompt: str) -> PromptOutcome:
    messages: list[RuntimeMessage] = []
    terminal_stop_reason: str | None = None
    terminal_metadata: dict[str, Any] = {}
    session.enqueue_event(InboundEvent(InboundEventType.USER_PROMPT, prompt))
    async for event in session.stream_until_idle():
        if event.event_type == TurnStreamEventType.MESSAGE and event.message is not None:
            messages.append(event.message)
        elif event.event_type == TurnStreamEventType.TERMINAL and event.terminal is not None:
            terminal_stop_reason = event.terminal.stop_reason
            terminal_metadata = dict(event.terminal.metadata)
    return PromptOutcome(
        messages=tuple(messages),
        terminal_stop_reason=terminal_stop_reason,
        terminal_metadata=terminal_metadata,
    )


async def _handle_local_command(
    *,
    command: LocalShellCommand,
    bound,
    layout: CodeAssistantLayout,
    session_id: str,
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
            await _inspect_demo_async(layout=layout),
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
        focus = f" Focus on: {command.argument}." if command.argument else ""
        return LocalCommandOutcome(
            dispatch_prompt=(
                "Review the current workspace. Ask the reviewer agent to inspect the latest "
                f"change and summarize the highest-risk findings.{focus}"
            )
        )
    if command.name == "verify":
        focus = f" Focus on: {command.argument}." if command.argument else ""
        return LocalCommandOutcome(
            dispatch_prompt=(
                "Verify the current workspace. Run the most relevant command with bash, inspect "
                f"related background jobs if needed, and summarize pass or fail.{focus}"
            )
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
    if report.transcript_sessions:
        latest = report.transcript_sessions[0]
        output_writer(
            f"latest transcript: {latest['session_id']} "
            f"({_display_path(Path(latest['path']))}, {latest['entries']} entries)"
        )
    output_writer(f"child run sessions: {len(report.child_run_sessions)}")
    output_writer(f"task lists: {len(report.task_lists)}")
    if report.memory_root is not None:
        output_writer(f"memory root: {_display_path(report.memory_root)}")
        output_writer(f"memory documents: {report.memory_documents}")


def _print_task_list(*, task_list: dict[str, Any], output_writer) -> None:
    tasks = task_list.get("tasks", [])
    output_writer(f"task list: {task_list.get('task_list_id', '<unknown>')}")
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
        if kind == "background_shell" and status in {"pending", "running"}:
            command = str(metadata.get("command") or "").strip()
            job_id = str(job.get("job_id") or "").strip()
            job_suffix = f", job={job_id}" if job_id else ""
            output_writer(f"[bash:running] {classification}{job_suffix} {command}".rstrip())
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

    skill_result = _find_skill_result(messages, skill_name="coding-loop")
    if skill_result is None:
        gaps.append("the workspace-local coding-loop skill was not applied")
    elif skill_result.get("mode") != "inline":
        gaps.append("the workspace-local coding-loop skill did not run inline")

    approval_names = {approval.name for approval in approvals}
    for tool_name in ("edit", "write", "bash"):
        if tool_name not in approval_names:
            gaps.append(f"host approval for {tool_name} was never recorded")

    child_statuses: dict[str, str] = {}
    for child in child_runs:
        agent_name = str(child.get("agent") or "").strip()
        status = str(child.get("status") or "").strip()
        if agent_name:
            child_statuses[agent_name] = status
    for agent_name in ("coding-planner", "reviewer", "verifier"):
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


def _session_child_runs(records: list[dict[str, Any]], *, session_id: str) -> list[dict[str, Any]]:
    return [record for record in records if str(record.get("session_id") or "") == session_id]


__all__ = [
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
