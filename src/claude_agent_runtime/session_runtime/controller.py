from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any, AsyncIterator
from uuid import uuid4

from ..compaction import latest_compaction_payload
from ..contracts import (
    MessageAttachment,
    MessageRole,
    RuntimeMessage,
    private_context_from_legacy_runtime_context,
    SessionCommand,
    SessionCommandType,
    SessionState,
    SessionStatus,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)
from ..definitions import AgentDefinition, PermissionMode
from ..memory.models import MemoryTurnResult, MemoryWriteReceipt, normalize_memory_segment
from ..hooks import SessionEndPayload, SessionStartPayload
from ..memory.schema import SESSION_MANIFEST_KIND, build_manifest_envelope
from ..permissions import PermissionContext
from ..runtime_services import DefaultTranscriptService, RuntimeServices
from ..tool_runtime import SessionScope
from ..turn_engine.engine import TurnEngine, TurnStreamEvent, TurnStreamEventType
from ..turn_engine.models import TranscriptEntry, TranscriptSession, TranscriptStore
from .ingress import SessionIngressProcessor
from .models import IngressReplayOutput, SessionIngressSnapshot


class InboundEventType(StrEnum):
    USER_PROMPT = "user_prompt"
    SYSTEM_MESSAGE = "system_message"
    TASK_NOTIFICATION = "task_notification"
    HOST_EVENT = "host_event"


@dataclass(frozen=True, slots=True)
class InboundEvent:
    event_type: InboundEventType
    content: str
    metadata: dict[str, object] = field(default_factory=dict)


class SessionController:
    def __init__(
        self,
        *,
        session_id: str,
        agent: AgentDefinition,
        turn_engine: TurnEngine,
        transcript_store: TranscriptStore,
        cwd: str,
        system_prompt: str,
        runtime_services: RuntimeServices | None = None,
        ingress_processor: SessionIngressProcessor | None = None,
        close_callback: Any = None,
    ) -> None:
        self.state = SessionState(session_id=session_id, current_agent=agent.name)
        self._agent = agent
        self._turn_engine = turn_engine
        self._runtime_services = runtime_services or RuntimeServices(
            transcript=DefaultTranscriptService(transcript_store)
        )
        if self._runtime_services.transcript is None:
            self._runtime_services.transcript = DefaultTranscriptService(transcript_store)
        self._transcript_store = self._runtime_services.transcript_store
        self._cwd = cwd
        self._system_prompt = system_prompt
        self._messages: list[RuntimeMessage] = []
        self._ingress_processor = ingress_processor or SessionIngressProcessor()
        self._started = False
        self._closed = False
        self._close_task: asyncio.Task[None] | None = None
        self._close_callback = close_callback
        self._session_private_context: dict[str, Any] = {}
        self.state.metadata.setdefault(
            "permission_context",
            PermissionContext(
                session_id=session_id,
                mode=agent.permission_mode or PermissionMode.DEFAULT,
            ),
        )
        self._session_scope = SessionScope(
            session_id=session_id,
            agent_name=agent.name,
            cwd=Path(cwd),
            private_context=self._session_scope_private_context(),
            task_manager=self._runtime_services.task_manager,
        )

    @property
    def messages(self) -> tuple[RuntimeMessage, ...]:
        return tuple(self._messages)

    @property
    def cwd(self) -> str:
        return self._cwd

    @property
    def runtime_services(self) -> RuntimeServices:
        return self._runtime_services

    def resolve_invocations(self):
        return self._turn_engine.resolve_invocation_catalog(
            session_id=self.state.session_id,
            turn_id=self.state.active_turn_id,
            cwd=self._cwd,
            messages=self.messages,
            runtime_context=dict(self.state.metadata),
        )

    def visible_invocations(
        self,
        *,
        user_invocable: bool | None = None,
        model_invocable: bool | None = None,
    ):
        return self.resolve_invocations().visible_capabilities(
            user_invocable=user_invocable,
            model_invocable=model_invocable,
        )

    def invocation_diagnostics(self):
        return self.resolve_invocations().diagnostics

    async def start(self) -> None:
        if not self._started:
            memory_service = self._runtime_services.memory
            if memory_service is not None and hasattr(memory_service, "start_session"):
                await _maybe_await(
                    memory_service.start_session(
                        session_id=self.state.session_id,
                        agent=self._agent,
                        cwd=self._cwd,
                        set_default=True,
                    )
                )
            self._ensure_session_memory_artifacts(status="active")
            await self._runtime_services.hook_bus.dispatch(
                self.state.session_id,
                SessionStartPayload(session_id=self.state.session_id),
            )
            self._started = True
        self.state.status = SessionStatus.READY

    def normalize_event(self, event: InboundEvent) -> SessionCommand:
        priority_map = {
            InboundEventType.USER_PROMPT: 10,
            InboundEventType.SYSTEM_MESSAGE: 50,
            InboundEventType.TASK_NOTIFICATION: 40,
            InboundEventType.HOST_EVENT: 30,
        }
        command_type = {
            InboundEventType.USER_PROMPT: SessionCommandType.USER_PROMPT,
            InboundEventType.SYSTEM_MESSAGE: SessionCommandType.SYSTEM_MESSAGE,
            InboundEventType.TASK_NOTIFICATION: SessionCommandType.TASK_NOTIFICATION,
            InboundEventType.HOST_EVENT: SessionCommandType.HOST_EVENT,
        }[event.event_type]
        return SessionCommand(
            command_id=uuid4().hex,
            command_type=command_type,
            payload={"content": event.content, "metadata": event.metadata},
            priority=priority_map[event.event_type],
        )

    def enqueue_event(self, event: InboundEvent) -> None:
        command = self.normalize_event(event)
        self.state.queued_commands.append(command)
        self.state.queued_commands.sort(key=lambda item: (-item.priority, item.created_at))

    def interrupt(self, reason: str = "interrupt") -> None:
        self.state.status = SessionStatus.INTERRUPTED
        self._turn_engine.interrupt(reason)

    async def resume(self) -> None:
        transcript = await self._transcript_store.load(self.state.session_id)
        self._messages = [entry.message for entry in transcript.entries]
        self._sync_compaction_state()
        self.state.status = SessionStatus.READY
        self.state.active_turn_id = None

    async def close(self, final_status: str = "completed") -> None:
        if self._closed:
            return
        current_task = asyncio.current_task()
        if self._close_task is not None:
            if self._close_task is current_task:
                return
            await asyncio.shield(self._close_task)
            return
        if current_task is None:  # pragma: no cover - defensive async boundary
            raise RuntimeError("SessionController.close() requires an active asyncio task")

        self._close_task = current_task
        error: Exception | None = None
        try:
            self._update_session_memory_status(final_status)
            background_consolidation_task_id = await self._schedule_background_memory_consolidation()
            if background_consolidation_task_id is not None:
                history = self.state.metadata.setdefault("background_memory_consolidation_tasks", [])
                if isinstance(history, list):
                    history.append(background_consolidation_task_id)
            await self._runtime_services.hook_bus.dispatch(
                self.state.session_id,
                SessionEndPayload(
                    session_id=self.state.session_id,
                    final_status=final_status,
                ),
            )
        except Exception as exc:
            error = exc
        finally:
            self._started = False
            self._closed = True
            self.state.active_turn_id = None
            self.state.status = _session_status_for_close(final_status)
            try:
                if self._runtime_services.hook_bus is not None:
                    self._runtime_services.hook_bus.clear_session(self.state.session_id)
            except Exception as exc:
                if error is None:
                    error = exc
            try:
                if self._close_callback is not None:
                    await _maybe_await(self._close_callback(self, final_status))
            except Exception as exc:
                if error is None:
                    error = exc
            self._close_task = None

        if error is not None:
            raise error

    async def stream_until_idle(self) -> AsyncIterator[TurnStreamEvent]:
        if self.state.status == SessionStatus.IDLE:
            await self.start()

        while self.state.queued_commands:
            command = self.state.queued_commands.pop(0)
            prior_status = self.state.status
            ingress_result = self._ingress_processor.process(
                self._inbound_event_from_command(command),
                session_snapshot=self._ingress_snapshot(),
                runtime_services=self._runtime_services,
            )
            if ingress_result.admits_turn:
                self.state.status = SessionStatus.RUNNING
                self.state.active_turn_id = uuid4().hex
                record_turn_id = self.state.active_turn_id
            else:
                record_turn_id = uuid4().hex if ingress_result.normalized_messages else None
                self.state.active_turn_id = None
            await self._record_ingress_messages(
                ingress_result.normalized_messages,
                turn_id=record_turn_id,
            )
            if not ingress_result.admits_turn:
                self._apply_ingress_private_updates(ingress_result.private_updates)
            await self._emit_ingress_replay_outputs(ingress_result.replay_outputs)
            if not ingress_result.admits_turn:
                if self.state.status != SessionStatus.WAITING:
                    self.state.status = SessionStatus.READY
                continue

            last_terminal = None
            turn_retrieval_trace: dict[str, Any] | None = None
            turn_message_ids: list[str] = [message.message_id for message in ingress_result.normalized_messages]
            runtime_context = self._base_runtime_private_context()
            runtime_context.update(
                {
                    str(key): _copy_ingress_private_value(value)
                    for key, value in ingress_result.private_updates.items()
                }
            )
            runtime_context.update(
                {
                    "command_type": command.command_type.value,
                    "query_source": command.command_type.value,
                    "permission_context": runtime_context.get(
                        "permission_context",
                        self.state.metadata.get("permission_context"),
                    ),
                    "prompt_updates": dict(ingress_result.prompt_updates),
                }
            )
            continuation = self.state.metadata.get("compaction_continuation")
            if isinstance(continuation, dict):
                runtime_context["compaction_continuation"] = dict(continuation)
            self._session_scope.private_context = self._session_scope_private_context()
            self._session_scope.agent_name = self._agent.name
            self._session_scope.cwd = Path(self._cwd)
            self._session_scope.task_manager = self._runtime_services.task_manager
            async for event in self._turn_engine.run_turn_stream(
                session_id=self.state.session_id,
                turn_id=self.state.active_turn_id,
                agent=self._agent,
                cwd=self._cwd,
                messages=list(self._messages),
                base_system_prompt=self._system_prompt,
                attachments=list(_attachments_from_messages(ingress_result.normalized_messages)),
                runtime_context=runtime_context,
                session_scope=self._session_scope,
            ):
                if event.event_type == TurnStreamEventType.COMPACTION and event.compacted_messages:
                    await self._apply_compaction(
                        event.compacted_messages,
                        turn_id=self.state.active_turn_id,
                    )
                if event.event_type == TurnStreamEventType.MESSAGE and event.message is not None:
                    await self._record_message(
                        event.message,
                        turn_id=self.state.active_turn_id,
                    )
                    turn_message_ids.append(event.message.message_id)
                if event.event_type == TurnStreamEventType.REQUEST_START and event.request is not None:
                    retrieval_trace = _memory_retrieval_trace_from_request(event.request)
                    if retrieval_trace is not None:
                        turn_retrieval_trace = retrieval_trace
                        self.state.metadata["last_memory_retrieval"] = retrieval_trace
                await self._runtime_services.host.emit_turn_event(self.state.session_id, event)
                if event.event_type == TurnStreamEventType.TERMINAL and event.terminal is not None:
                    last_terminal = event.terminal
                    status_hint = _terminal_session_status_hint(event.terminal)
                    if status_hint == "waiting":
                        self.state.status = SessionStatus.WAITING
                    elif status_hint == "interrupted":
                        self.state.status = SessionStatus.INTERRUPTED
                yield event
            current_turn_ids = set(turn_message_ids)
            turn_messages = tuple(message for message in self._messages if message.message_id in current_turn_ids)
            if (
                command.command_type == SessionCommandType.USER_PROMPT
            ):
                if self.state.status != SessionStatus.WAITING and not _memory_updates_owned(
                    ingress_result.private_updates,
                    turn_messages,
                ):
                    await self._persist_turn_memory(
                        turn_messages,
                        terminal=last_terminal,
                        retrieval_trace=turn_retrieval_trace,
                    )
                self._refresh_session_memory(
                    turn_messages,
                    terminal=last_terminal,
                    prior_status=prior_status,
                )
            self.state.active_turn_id = None
            if self.state.status == SessionStatus.INTERRUPTED:
                break
            if self.state.status != SessionStatus.WAITING:
                self.state.status = SessionStatus.READY

    async def run_until_idle(self) -> tuple[RuntimeMessage, ...]:
        produced: list[RuntimeMessage] = []
        async for event in self.stream_until_idle():
            if event.event_type == TurnStreamEventType.MESSAGE and event.message is not None:
                produced.append(event.message)
        return tuple(produced)

    async def _record_message(
        self,
        message: RuntimeMessage,
        *,
        turn_id: str | None,
    ) -> None:
        self._messages.append(message)
        await self._transcript_store.append(
            TranscriptEntry(
                session_id=self.state.session_id,
                turn_id=turn_id,
                message=message,
            )
        )
        self._sync_compaction_state()

    async def _record_ingress_messages(
        self,
        messages: tuple[RuntimeMessage, ...],
        *,
        turn_id: str | None,
    ) -> None:
        for message in messages:
            await self._record_message(message, turn_id=turn_id)

    async def _emit_ingress_replay_outputs(
        self,
        replay_outputs: tuple[IngressReplayOutput, ...],
    ) -> None:
        for output in replay_outputs:
            await self._runtime_services.host.emit_notification(
                RuntimeMessage(
                    message_id=output.output_id,
                    role=output.role,
                    content=output.content,
                    metadata={
                        **output.metadata,
                        "source": output.source,
                        "visibility": output.visibility,
                        "ingress_replay": True,
                    },
                )
            )

    def _apply_ingress_private_updates(self, private_updates: dict[str, Any]) -> None:
        for key, value in private_updates.items():
            normalized_key = str(key)
            copied_value = _copy_ingress_private_value(value)
            self._session_private_context[normalized_key] = _copy_ingress_private_value(
                copied_value
            )
            self.state.metadata[normalized_key] = copied_value
        self._session_scope.private_context = self._session_scope_private_context()

    def _base_runtime_private_context(self) -> dict[str, Any]:
        return {
            str(key): _copy_ingress_private_value(value)
            for key, value in self._session_private_context.items()
        }

    def _session_scope_private_context(self):
        return private_context_from_legacy_runtime_context(
            {
                **self._base_runtime_private_context(),
                "permission_context": self.state.metadata.get("permission_context"),
            }
        )

    def _ingress_snapshot(self) -> SessionIngressSnapshot:
        return SessionIngressSnapshot.from_state(
            self.state,
            cwd=self._cwd,
            messages=self.messages,
        )

    def _inbound_event_from_command(self, command: SessionCommand) -> InboundEvent:
        event_type = {
            SessionCommandType.USER_PROMPT: InboundEventType.USER_PROMPT,
            SessionCommandType.SYSTEM_MESSAGE: InboundEventType.SYSTEM_MESSAGE,
            SessionCommandType.TASK_NOTIFICATION: InboundEventType.TASK_NOTIFICATION,
            SessionCommandType.HOST_EVENT: InboundEventType.HOST_EVENT,
        }[command.command_type]
        metadata = command.payload.get("metadata")
        return InboundEvent(
            event_type=event_type,
            content=str(command.payload.get("content", "")),
            metadata=dict(metadata) if isinstance(metadata, dict) else {},
        )

    async def _apply_compaction(
        self,
        messages: tuple[RuntimeMessage, ...],
        *,
        turn_id: str | None,
    ) -> None:
        transcript = await self._transcript_store.load(self.state.session_id)
        existing_entries = {entry.message.message_id: entry for entry in transcript.entries}
        rewritten_entries: list[TranscriptEntry] = []
        for message in messages:
            existing = existing_entries.get(message.message_id)
            if existing is not None:
                rewritten_entries.append(
                    TranscriptEntry(
                        session_id=existing.session_id,
                        turn_id=existing.turn_id,
                        message=message,
                        created_at=existing.created_at,
                    )
                )
                continue
            rewritten_entries.append(
                TranscriptEntry(
                    session_id=self.state.session_id,
                    turn_id=turn_id,
                    message=message,
                )
            )
        self._messages = list(messages)
        await self._transcript_store.replace(
            TranscriptSession(
                session_id=self.state.session_id,
                entries=tuple(rewritten_entries),
            )
        )
        self._sync_compaction_state()
        self._record_session_compaction()

    async def _persist_turn_memory(
        self,
        messages: tuple[RuntimeMessage, ...],
        *,
        terminal: Any,
        retrieval_trace: dict[str, Any] | None = None,
    ) -> None:
        if not _turn_effect_enabled(terminal, "persist_memory"):
            return
        memory_service = self._runtime_services.memory
        if memory_service is None or not hasattr(memory_service, "record_turn"):
            return
        if hasattr(memory_service, "record_turn_with_receipts"):
            turn_result = await _maybe_await(
                memory_service.record_turn_with_receipts(
                    session_id=self.state.session_id,
                    agent=self._agent,
                    cwd=self._cwd,
                    messages=messages,
                )
            )
        else:
            persisted = await _maybe_await(
                memory_service.record_turn(
                    session_id=self.state.session_id,
                    agent=self._agent,
                    cwd=self._cwd,
                    messages=messages,
                )
            )
            turn_result = MemoryTurnResult(persisted_documents=tuple(persisted), receipts=())
        receipt_payloads = [_memory_write_receipt_payload(receipt) for receipt in turn_result.receipts]
        if receipt_payloads:
            history = self.state.metadata.setdefault("memory_write_receipts", [])
            if isinstance(history, list):
                history.extend(receipt_payloads)
        self._record_session_memory_deltas(
            persisted=turn_result.persisted_documents,
            receipts=turn_result.receipts,
        )
        background_task_id = await self._schedule_background_memory_extraction(messages, terminal=terminal)
        if background_task_id is not None:
            history = self.state.metadata.setdefault("background_memory_tasks", [])
            if isinstance(history, list):
                history.append(background_task_id)
        diagnostics_payload: dict[str, object] = {"turn_id": str(self.state.active_turn_id or "")}
        if retrieval_trace is not None:
            diagnostics_payload["retrieval"] = dict(retrieval_trace)
        if receipt_payloads:
            diagnostics_payload["write_receipts"] = list(receipt_payloads)
        if background_task_id is not None:
            diagnostics_payload["background_task_id"] = background_task_id
        if len(diagnostics_payload) > 1:
            history = self.state.metadata.setdefault("memory_diagnostics", [])
            if isinstance(history, list):
                history.append(diagnostics_payload)
        persisted = turn_result.persisted_documents
        if not persisted:
            return

        records = [
            {"path": str(document.path), "scope": document.scope.value, "title": document.title}
            for document in persisted
        ]
        history = self.state.metadata.setdefault("memory_updates", [])
        if isinstance(history, list):
            history.extend(records)

        summary = ", ".join(document.title for document in persisted[:2])
        if len(persisted) > 2:
            summary = f"{summary}, ..."
        notification = RuntimeMessage(
            message_id=uuid4().hex,
            role=MessageRole.NOTIFICATION,
            content=(
                f"Saved {len(persisted)} memory update(s) to {persisted[0].scope.value} scope"
                + (f": {summary}" if summary else "")
            ),
            metadata={
                "memory_update": True,
                "memory_update_owned": True,
                "memory_scope": persisted[0].scope.value,
                "memory_paths": [str(document.path) for document in persisted],
                "memory_write_receipts": receipt_payloads,
                "memory_diagnostics": diagnostics_payload,
            },
        )
        await self._runtime_services.host.emit_notification(notification)

    async def _schedule_background_memory_extraction(
        self,
        messages: tuple[RuntimeMessage, ...],
        *,
        terminal: Any,
    ) -> str | None:
        if not _turn_effect_enabled(terminal, "schedule_background_extraction"):
            return None
        memory_service = self._runtime_services.memory
        if memory_service is None or not hasattr(memory_service, "schedule_background_extraction"):
            return None
        task_id = await _maybe_await(
            memory_service.schedule_background_extraction(
                session_id=self.state.session_id,
                agent=self._agent,
                cwd=self._cwd,
                messages=tuple(self._messages),
                task_manager=self._runtime_services.task_manager,
            )
        )
        return str(task_id) if task_id is not None else None

    async def _schedule_background_memory_consolidation(self) -> str | None:
        memory_service = self._runtime_services.memory
        if memory_service is None or not hasattr(memory_service, "schedule_background_consolidation"):
            return None
        task_id = await _maybe_await(
            memory_service.schedule_background_consolidation(
                session_id=self.state.session_id,
                agent=self._agent,
                cwd=self._cwd,
                task_manager=self._runtime_services.task_manager,
            )
        )
        return str(task_id) if task_id is not None else None

    def _resolve_session_memory_context(self):
        memory_service = self._runtime_services.memory
        if memory_service is None or not hasattr(memory_service, "resolve_context"):
            return None
        return memory_service.resolve_context(
            session_id=self.state.session_id,
            agent=self._agent,
            cwd=self._cwd,
        )

    def _ensure_session_memory_artifacts(self, *, status: str) -> None:
        context = self._resolve_session_memory_context()
        if context is None:
            return
        session_root = context.session_root()
        checkpoints_dir = session_root / "checkpoints"
        session_root.mkdir(parents=True, exist_ok=True)
        checkpoints_dir.mkdir(parents=True, exist_ok=True)

        if not context.session_open_threads_path().exists():
            context.session_open_threads_path().write_text("# Open Threads\n\n", encoding="utf-8")

        metadata = _default_session_metadata(
            session_id=self.state.session_id,
            status=status,
        )
        existing_metadata = _read_json_file(context.session_metadata_path())
        if isinstance(existing_metadata, dict):
            metadata.update(existing_metadata)
        metadata["status"] = status
        metadata["updated_at"] = _utc_now_iso()
        metadata["open_thread_count"] = _count_open_threads(context.session_open_threads_path())
        _write_json_file(context.session_metadata_path(), metadata)
        _upsert_session_manifest(context, metadata)

    def _update_session_memory_status(self, status: str) -> None:
        context = self._resolve_session_memory_context()
        if context is None:
            return
        self._ensure_session_memory_artifacts(status=status)
        metadata = _read_json_file(context.session_metadata_path())
        if not isinstance(metadata, dict):
            metadata = _default_session_metadata(session_id=self.state.session_id, status=status)
        metadata["status"] = status
        metadata["updated_at"] = _utc_now_iso()
        metadata["open_thread_count"] = _count_open_threads(context.session_open_threads_path())
        _write_json_file(context.session_metadata_path(), metadata)
        _upsert_session_manifest(context, metadata)

    def _record_session_compaction(self) -> None:
        context = self._resolve_session_memory_context()
        if context is None:
            return
        metadata = _read_json_file(context.session_metadata_path())
        if not isinstance(metadata, dict):
            metadata = _default_session_metadata(session_id=self.state.session_id, status="active")
        metadata["last_compaction_at"] = _utc_now_iso()
        metadata["updated_at"] = metadata["last_compaction_at"]
        metadata["open_thread_count"] = _count_open_threads(context.session_open_threads_path())
        _write_json_file(context.session_metadata_path(), metadata)
        _upsert_session_manifest(context, metadata)

    def _refresh_session_memory(
        self,
        messages: tuple[RuntimeMessage, ...],
        *,
        terminal: Any,
        prior_status: SessionStatus,
    ) -> None:
        if not _turn_effect_enabled(terminal, "refresh_session_state"):
            return
        context = self._resolve_session_memory_context()
        if context is None:
            return

        self._ensure_session_memory_artifacts(
            status="waiting" if self.state.status == SessionStatus.WAITING else "active"
        )
        metadata = _read_json_file(context.session_metadata_path())
        if not isinstance(metadata, dict):
            metadata = _default_session_metadata(session_id=self.state.session_id, status="active")

        metadata["status"] = "waiting" if self.state.status == SessionStatus.WAITING else "active"
        updated_at = _utc_now_iso()
        metadata["updated_at"] = updated_at
        metadata["turns_since_summary"] = int(metadata.get("turns_since_summary", 0)) + 1
        metadata["chars_since_summary"] = int(metadata.get("chars_since_summary", 0)) + sum(
            len(message.text.strip()) for message in messages if message.text.strip()
        )
        metadata["tool_calls_since_summary"] = int(metadata.get("tool_calls_since_summary", 0)) + _count_tool_events(
            messages
        )

        open_threads_path = context.session_open_threads_path()
        existing_threads = _read_open_threads(open_threads_path)
        open_threads = _reconcile_open_threads(
            path=open_threads_path,
            existing_threads=existing_threads,
            candidate=_session_thread_candidate(
                messages=messages,
                agent_name=self._agent.name,
                terminal=terminal,
            ),
            agent_name=self._agent.name,
            prior_status=prior_status,
            prompt_text=_primary_user_prompt_text(messages),
        )
        open_threads_changed = open_threads != existing_threads
        metadata["open_thread_count"] = len(open_threads)
        refresh_thresholds = self._session_summary_thresholds()

        if _should_refresh_session_summary(
            context,
            metadata,
            refresh_thresholds=refresh_thresholds,
            open_threads_changed=open_threads_changed,
            prior_status=prior_status,
        ):
            context.session_summary_path().write_text(
                _render_session_summary(
                    session_id=self.state.session_id,
                    agent_name=self._agent.name,
                    turn_id=self.state.active_turn_id,
                    messages=self._messages,
                    open_threads=open_threads,
                    status=metadata["status"],
                    updated_at=updated_at,
                ),
                encoding="utf-8",
            )
            metadata["summary_version"] = int(metadata.get("summary_version", 0)) + 1
            metadata["last_summary_refresh_at"] = updated_at
            metadata["turns_since_summary"] = 0
            metadata["chars_since_summary"] = 0
            metadata["tool_calls_since_summary"] = 0

        _write_json_file(context.session_metadata_path(), metadata)
        _upsert_session_manifest(context, metadata)

    def _session_summary_thresholds(self) -> dict[str, int]:
        memory_service = self._runtime_services.memory
        if memory_service is None or not hasattr(memory_service, "session_summary_thresholds"):
            return {
                "token_growth_threshold": _SESSION_SUMMARY_CHAR_THRESHOLD,
                "tool_call_threshold": _SESSION_SUMMARY_TOOL_CALL_THRESHOLD,
                "turn_threshold": _SESSION_SUMMARY_TURN_THRESHOLD,
            }
        thresholds = memory_service.session_summary_thresholds(
            session_id=self.state.session_id,
            agent=self._agent,
            cwd=self._cwd,
        )
        return thresholds if isinstance(thresholds, dict) else {
            "token_growth_threshold": _SESSION_SUMMARY_CHAR_THRESHOLD,
            "tool_call_threshold": _SESSION_SUMMARY_TOOL_CALL_THRESHOLD,
            "turn_threshold": _SESSION_SUMMARY_TURN_THRESHOLD,
        }

    def _record_session_memory_deltas(
        self,
        *,
        persisted: tuple[MemoryDocument, ...],
        receipts: tuple[MemoryWriteReceipt, ...],
    ) -> None:
        if not persisted:
            return
        context = self._resolve_session_memory_context()
        if context is None:
            return
        metadata = _read_json_file(context.session_metadata_path())
        if not isinstance(metadata, dict):
            metadata = _default_session_metadata(session_id=self.state.session_id, status="active")
        existing = metadata.get("durable_memory_deltas", [])
        durable_deltas = [entry for entry in existing if isinstance(entry, dict)] if isinstance(existing, list) else []
        known_paths = {
            str(entry.get("path"))
            for entry in durable_deltas
            if isinstance(entry.get("path"), str)
        }
        receipts_by_path = {
            str(receipt.path): receipt
            for receipt in receipts
            if receipt.path is not None
        }
        for document in persisted:
            if not document.path.is_relative_to(context.documents_dir):
                continue
            path = str(document.path)
            if path in known_paths:
                continue
            receipt = receipts_by_path.get(path)
            durable_deltas.append(
                {
                    "path": document.path.relative_to(context.memory_root).as_posix(),
                    "memory_kind": document.kind,
                    "title": document.title,
                    "conflict_key": document.metadata.get("conflict_key"),
                    "source_pathway": receipt.source_pathway if receipt is not None else document.metadata.get("source_pathway"),
                }
            )
            known_paths.add(path)
        metadata["durable_memory_deltas"] = durable_deltas
        metadata["durable_memory_delta_count"] = len(durable_deltas)
        _write_json_file(context.session_metadata_path(), metadata)
        _upsert_session_manifest(context, metadata)

    def _sync_compaction_state(self) -> None:
        payload = latest_compaction_payload(self._messages)
        if payload is None:
            self.state.metadata.pop("compaction", None)
            self.state.metadata.pop("compaction_summary", None)
            self.state.metadata.pop("compaction_boundary", None)
            self.state.metadata.pop("compaction_continuation", None)
            return
        self.state.metadata["compaction"] = payload
        summary = payload.get("summary")
        boundary = payload.get("boundary")
        continuation = payload.get("continuation")
        if isinstance(summary, dict):
            self.state.metadata["compaction_summary"] = dict(summary)
        else:
            self.state.metadata.pop("compaction_summary", None)
        if isinstance(boundary, dict):
            self.state.metadata["compaction_boundary"] = dict(boundary)
        else:
            self.state.metadata.pop("compaction_boundary", None)
        if isinstance(continuation, dict):
            self.state.metadata["compaction_continuation"] = dict(continuation)
        else:
            self.state.metadata.pop("compaction_continuation", None)


def _turn_effect_enabled(terminal: Any, effect_name: str) -> bool:
    if terminal is None:
        return False
    post_effects = getattr(terminal, "post_effects", None)
    if post_effects is None:
        return False
    return bool(getattr(post_effects, effect_name, False))


def _terminal_session_status_hint(terminal: Any) -> str | None:
    if terminal is None:
        return None
    post_effects = getattr(terminal, "post_effects", None)
    if post_effects is None:
        return None
    hint = getattr(post_effects, "session_status_hint", None)
    return str(hint) if hint is not None else None


def _session_status_for_close(final_status: str) -> SessionStatus:
    normalized = final_status.strip().lower()
    if normalized in {"interrupt", "interrupted"}:
        return SessionStatus.INTERRUPTED
    if normalized in {"error", "failed", "failure"}:
        return SessionStatus.FAILED
    if normalized in {"stopped", "blocked"}:
        return SessionStatus.STOPPED
    return SessionStatus.COMPLETED


def _memory_updates_owned(
    metadata: object,
    messages: tuple[RuntimeMessage, ...],
) -> bool:
    if isinstance(metadata, dict) and metadata.get("memory_update_owned"):
        return True
    return any(message.metadata.get("memory_update_owned") for message in messages)


def _memory_write_receipt_payload(receipt: MemoryWriteReceipt) -> dict[str, object]:
    payload: dict[str, object] = {
        "fact_type": receipt.fact_type,
        "action": receipt.action,
        "scope": receipt.scope,
        "target_layer": receipt.target_layer,
        "namespace": receipt.namespace,
        "retention": receipt.retention,
        "merge_policy": receipt.merge_policy,
        "source_message_ids": list(receipt.source_message_ids),
        "source_roles": list(receipt.source_roles),
    }
    if receipt.title is not None:
        payload["title"] = receipt.title
    if receipt.path is not None:
        payload["path"] = str(receipt.path)
    if receipt.reason is not None:
        payload["reason"] = receipt.reason
    if receipt.source_pathway is not None:
        payload["source_pathway"] = receipt.source_pathway
    if receipt.conflict_key is not None:
        payload["conflict_key"] = receipt.conflict_key
    if receipt.contested:
        payload["contested"] = True
    if receipt.supersedes:
        payload["supersedes"] = list(receipt.supersedes)
    return payload


def _memory_retrieval_trace_from_request(request: object) -> dict[str, Any] | None:
    private_context = getattr(request, "private_context", None)
    diagnostics = getattr(private_context, "diagnostics", None)
    if isinstance(diagnostics, dict):
        retrieval = diagnostics.get("memory_diagnostics")
        if isinstance(retrieval, dict):
            nested = retrieval.get("retrieval")
            if isinstance(nested, dict):
                return dict(nested)
        direct = diagnostics.get("memory_retrieval")
        if isinstance(direct, dict):
            return dict(direct)
    request_metadata = getattr(request, "metadata", None)
    if isinstance(request_metadata, dict):
        diagnostics = request_metadata.get("memory_diagnostics")
        if isinstance(diagnostics, dict):
            retrieval = diagnostics.get("retrieval")
            if isinstance(retrieval, dict):
                return dict(retrieval)
        retrieval = request_metadata.get("memory_retrieval")
        if isinstance(retrieval, dict):
            return dict(retrieval)
    turn_context = getattr(request, "turn_context", None)
    metadata = getattr(turn_context, "metadata", None)
    if not isinstance(metadata, dict):
        return None
    diagnostics = metadata.get("memory_diagnostics")
    if isinstance(diagnostics, dict):
        retrieval = diagnostics.get("retrieval")
        if isinstance(retrieval, dict):
            return dict(retrieval)
    retrieval = metadata.get("memory_retrieval")
    if isinstance(retrieval, dict):
        return dict(retrieval)
    return None


def _attachments_from_messages(messages: tuple[RuntimeMessage, ...]) -> tuple[MessageAttachment, ...]:
    attachments: list[MessageAttachment] = []
    seen: set[tuple[str, str]] = set()
    for message in messages:
        for attachment in message.attachments:
            key = (attachment.name, attachment.path)
            if key in seen:
                continue
            seen.add(key)
            attachments.append(attachment)
    return tuple(attachments)


def _copy_ingress_private_value(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): _copy_ingress_private_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_copy_ingress_private_value(item) for item in value]
    return value


async def _maybe_await(value: Any) -> Any:
    if asyncio.iscoroutine(value):
        return await value
    return value


_SESSION_SUMMARY_TURN_THRESHOLD = 6
_SESSION_SUMMARY_CHAR_THRESHOLD = 4000
_SESSION_SUMMARY_TOOL_CALL_THRESHOLD = 8


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _default_session_metadata(*, session_id: str, status: str) -> dict[str, Any]:
    now = _utc_now_iso()
    return {
        "session_id": session_id,
        "status": status,
        "created_at": now,
        "updated_at": now,
        "summary_version": 0,
        "open_thread_count": 0,
        "last_compaction_at": None,
        "last_summary_refresh_at": None,
        "last_consolidated_at": None,
        "turns_since_summary": 0,
        "chars_since_summary": 0,
        "tool_calls_since_summary": 0,
        "durable_memory_delta_count": 0,
        "durable_memory_deltas": [],
    }


def _read_json_file(path: Path) -> dict[str, Any] | None:
    if not path.exists() or not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _write_json_file(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _upsert_session_manifest(context: Any, metadata: dict[str, Any]) -> None:
    existing_manifest = _read_json_file(context.session_manifest_path) or {}
    raw_sessions = existing_manifest.get("sessions", ())
    sessions = [entry for entry in raw_sessions if isinstance(entry, dict)] if isinstance(raw_sessions, list) else []
    session_root = context.session_root()
    checkpoint_count = len(list((session_root / "checkpoints").glob("*.json")))
    open_thread_count = _count_open_threads(context.session_open_threads_path())
    record = {
        "session_id": metadata.get("session_id", context.session_id),
        "status": metadata.get("status", "active"),
        "path": session_root.relative_to(context.memory_root).as_posix() + "/",
        "has_summary": context.session_summary_path().exists(),
        "has_open_threads": open_thread_count > 0,
        "open_thread_count": open_thread_count,
        "checkpoint_count": checkpoint_count,
        "last_updated_at": metadata.get("updated_at") or _utc_now_iso(),
        "ready_for_consolidation": metadata.get("status") not in {"active", "waiting"},
        "durable_memory_delta_count": int(metadata.get("durable_memory_delta_count", 0)),
    }
    if metadata.get("last_compaction_at"):
        record["last_compaction_at"] = metadata["last_compaction_at"]
    if metadata.get("last_consolidated_at"):
        record["last_consolidated_at"] = metadata["last_consolidated_at"]
    deduped = [entry for entry in sessions if entry.get("session_id") != record["session_id"]]
    deduped.append(record)
    deduped.sort(key=lambda entry: str(entry.get("session_id", "")))
    manifest = build_manifest_envelope(
        manifest_kind=SESSION_MANIFEST_KIND,
        boundary_scope=context.scope,
        payload_key="sessions",
        payload=deduped,
    )
    _write_json_file(context.session_manifest_path, manifest)


def _count_open_threads(path: Path) -> int:
    return len(_read_open_threads(path))


def _count_tool_events(messages: tuple[RuntimeMessage, ...]) -> int:
    total = 0
    for message in messages:
        total += sum(1 for block in message.content if isinstance(block, (ToolUseBlock, ToolResultBlock)))
    return total


def _should_refresh_session_summary(
    context: Any,
    metadata: dict[str, Any],
    *,
    refresh_thresholds: dict[str, int],
    open_threads_changed: bool = False,
    prior_status: SessionStatus | None = None,
) -> bool:
    if not context.session_summary_path().exists():
        return True
    if open_threads_changed:
        return True
    if prior_status == SessionStatus.WAITING and metadata.get("status") != "waiting":
        return True
    return (
        int(metadata.get("turns_since_summary", 0)) >= int(refresh_thresholds.get("turn_threshold", _SESSION_SUMMARY_TURN_THRESHOLD))
        or int(metadata.get("chars_since_summary", 0)) >= int(refresh_thresholds.get("token_growth_threshold", _SESSION_SUMMARY_CHAR_THRESHOLD))
        or int(metadata.get("tool_calls_since_summary", 0)) >= int(refresh_thresholds.get("tool_call_threshold", _SESSION_SUMMARY_TOOL_CALL_THRESHOLD))
    )


def _render_session_summary(
    *,
    session_id: str,
    agent_name: str,
    turn_id: str | None,
    messages: list[RuntimeMessage],
    open_threads: list[dict[str, str]],
    status: str,
    updated_at: str,
) -> str:
    objective = _latest_message_text(messages, role=MessageRole.USER) or "Continue the active session."
    assistant_update = _latest_message_text(messages, role=MessageRole.ASSISTANT) or "No assistant response recorded yet."
    decisions = _session_decisions(messages)
    current_state = [
        f"Session status: {status}.",
        f"Messages recorded: {len(messages)}.",
        f"Open threads: {len(open_threads)} active.",
        f"Latest assistant update: {_truncate_text(assistant_update)}",
    ]
    if open_threads:
        current_state.append(f"Most urgent thread: {_truncate_text(open_threads[0]['summary'])}")
    constraints = _session_constraints(messages, agent_name=agent_name, open_threads=open_threads)
    important_outcomes = _session_recent_outcomes(messages, open_threads=open_threads)
    next_steps = _session_next_steps(
        messages,
        status=status,
        open_threads=open_threads,
    )
    source_turn_id = turn_id or "unknown"
    return (
        "# Session Summary\n\n"
        "## Current Objective\n"
        f"- {_truncate_text(objective)}\n\n"
        "## Current State\n"
        + "".join(f"- {line}\n" for line in current_state)
        + "\n## Key Decisions\n"
        + "".join(f"- {line}\n" for line in decisions)
        + "\n## Active Constraints\n"
        + "".join(f"- {line}\n" for line in constraints)
        + "\n## Important Recent Outcomes\n"
        + "".join(f"- {line}\n" for line in important_outcomes)
        + "\n## Likely Next Steps\n"
        + "".join(f"- {line}\n" for line in next_steps)
        + "\n## Provenance\n"
        f"- session_id: {session_id}\n"
        f"- updated_at: {updated_at}\n"
        "- source_turn_ids:\n"
        f"  - {source_turn_id}\n"
    )


def _session_decisions(messages: list[RuntimeMessage]) -> list[str]:
    decisions = _collect_recent_message_texts(
        messages,
        roles=(MessageRole.NOTIFICATION, MessageRole.ASSISTANT),
        limit=3,
        include_questions=False,
    )
    return decisions or ["Continue from the latest confirmed turn output."]


def _session_constraints(
    messages: list[RuntimeMessage],
    *,
    agent_name: str,
    open_threads: list[dict[str, str]],
) -> list[str]:
    constraints = [f"Current agent: {agent_name}.", "Session continuity is tracked separately from transcript compaction."]
    constraints.extend(_recent_user_constraints(messages))
    if open_threads:
        constraints.append(f"Keep {len(open_threads)} open thread(s) in sync with follow-up turns.")
    return _dedupe_ordered(constraints)


def _session_recent_outcomes(
    messages: list[RuntimeMessage],
    *,
    open_threads: list[dict[str, str]],
) -> list[str]:
    outcomes = _collect_recent_message_texts(
        messages,
        roles=(MessageRole.NOTIFICATION, MessageRole.ASSISTANT),
        limit=3,
    )
    if open_threads:
        outcomes.append(f"Outstanding thread: {_truncate_text(open_threads[0]['summary'])}")
    return _dedupe_ordered(outcomes) or ["No assistant response recorded yet."]


def _session_next_steps(
    messages: list[RuntimeMessage],
    *,
    status: str,
    open_threads: list[dict[str, str]],
) -> list[str]:
    if open_threads:
        return _dedupe_ordered(
            [_truncate_text(thread["next_action"]) for thread in open_threads if thread.get("next_action")]
        ) or ["Resolve the active open thread before expanding scope."]
    if status == "waiting":
        return ["Wait for the blocker to clear or for new user input before continuing."]
    assistant_update = _latest_message_text(messages, role=MessageRole.ASSISTANT)
    if assistant_update.endswith("?"):
        return ["Wait for the user to answer the outstanding question."]
    return ["Continue the active objective from the latest confirmed state."]


def _collect_recent_message_texts(
    messages: list[RuntimeMessage],
    *,
    roles: tuple[MessageRole, ...],
    limit: int,
    include_questions: bool = True,
) -> list[str]:
    collected: list[str] = []
    seen: set[str] = set()
    for message in reversed(messages):
        if message.role not in roles or not message.text.strip():
            continue
        text = _truncate_text(message.text.strip())
        if not include_questions and text.endswith("?"):
            continue
        dedupe_key = text.lower()
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        collected.append(text)
        if len(collected) >= limit:
            break
    collected.reverse()
    return collected


def _recent_user_constraints(messages: list[RuntimeMessage]) -> list[str]:
    markers = ("prefer", "keep", "avoid", "use ", "must", "always", "never", "don't", "do not", "remember")
    constraints: list[str] = []
    for message in reversed(messages):
        if message.role != MessageRole.USER or not message.text.strip():
            continue
        text = " ".join(message.text.strip().split())
        lowered = text.lower()
        if any(marker in lowered for marker in markers):
            constraints.append(_truncate_text(text))
        if len(constraints) >= 2:
            break
    constraints.reverse()
    return constraints


def _dedupe_ordered(values: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = value.strip()
        if not normalized:
            continue
        dedupe_key = normalized.lower()
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        deduped.append(normalized)
    return deduped


def _latest_message_text(messages: list[RuntimeMessage], *, role: MessageRole) -> str:
    for message in reversed(messages):
        if message.role == role and message.text.strip():
            return message.text.strip()
    return ""


def _truncate_text(value: str, *, limit: int = 180) -> str:
    normalized = " ".join(value.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3].rstrip() + "..."


def _write_open_threads(path: Path, threads: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_render_open_threads(threads), encoding="utf-8")


def _reconcile_open_threads(
    *,
    path: Path,
    existing_threads: list[dict[str, str]],
    candidate: dict[str, str] | None,
    agent_name: str,
    prior_status: SessionStatus,
    prompt_text: str,
) -> list[dict[str, str]]:
    owner = normalize_memory_segment(agent_name, default="agent")
    prompt_subject = _thread_subject(prompt_text) if prompt_text else None
    candidate_subject = _thread_subject_from_key(candidate["thread_key"]) if candidate is not None else None
    resolved_keys: set[str] = set()
    for thread in existing_threads:
        if thread.get("owner") != owner:
            continue
        thread_key = thread.get("thread_key", "")
        if candidate is not None:
            if (
                candidate_subject is not None
                and _thread_subject_from_key(thread_key) == candidate_subject
                and thread_key != candidate["thread_key"]
            ):
                resolved_keys.add(thread_key)
            continue
        if thread.get("status") == "waiting_user":
            resolved_keys.add(thread_key)
            continue
        if prior_status == SessionStatus.WAITING and thread.get("status") == "blocked":
            resolved_keys.add(thread_key)
            continue
        if prompt_subject is not None and _thread_subject_from_key(thread_key) == prompt_subject:
            resolved_keys.add(thread_key)
    threads = [thread for thread in existing_threads if thread.get("thread_key") not in resolved_keys]
    if candidate is not None:
        threads = [thread for thread in threads if thread.get("thread_key") != candidate["thread_key"]]
        threads.append(candidate)
    threads.sort(key=lambda entry: entry["thread_key"])
    _write_open_threads(path, threads)
    return threads


def _thread_subject_from_key(thread_key: str) -> str | None:
    parts = thread_key.split(":", 2)
    if len(parts) != 3:
        return None
    return parts[1] or None


def _read_open_threads(path: Path) -> list[dict[str, str]]:
    if not path.exists() or not path.is_file():
        return []
    threads: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if raw_line.startswith("## Thread: "):
            if current is not None and _valid_open_thread(current):
                threads.append(current)
            current = {"thread_key": raw_line.removeprefix("## Thread: ").strip()}
            continue
        if current is None or not line.startswith("- "):
            continue
        if line.startswith("- Status: "):
            current["status"] = line.removeprefix("- Status: ").strip()
        elif line.startswith("- Owner: "):
            current["owner"] = line.removeprefix("- Owner: ").strip()
        elif line.startswith("- Summary: "):
            current["summary"] = line.removeprefix("- Summary: ").strip()
        elif line.startswith("- Next Action: "):
            current["next_action"] = line.removeprefix("- Next Action: ").strip()
        elif line.startswith("- Unblock Condition: "):
            current["unblock_condition"] = line.removeprefix("- Unblock Condition: ").strip()
    if current is not None and _valid_open_thread(current):
        threads.append(current)
    return threads


def _render_open_threads(threads: list[dict[str, str]]) -> str:
    sections = ["# Open Threads", ""]
    for thread in threads:
        sections.extend(
            [
                f"## Thread: {thread['thread_key']}",
                f"- Status: {thread['status']}",
                f"- Owner: {thread['owner']}",
                f"- Summary: {thread['summary']}",
                f"- Next Action: {thread['next_action']}",
                f"- Unblock Condition: {thread['unblock_condition']}",
                "",
            ]
        )
    return "\n".join(sections).rstrip() + "\n"


def _valid_open_thread(thread: dict[str, str]) -> bool:
    required = ("thread_key", "status", "owner", "summary", "next_action")
    return all(isinstance(thread.get(field), str) and thread[field].strip() for field in required)


def _session_thread_candidate(
    *,
    messages: tuple[RuntimeMessage, ...],
    agent_name: str,
    terminal: Any,
) -> dict[str, str] | None:
    prompt_text = _primary_user_prompt_text(messages)
    assistant_text = _latest_message_text(list(messages), role=MessageRole.ASSISTANT)
    owner = normalize_memory_segment(agent_name, default="agent")
    if terminal is not None and terminal.stop_reason == "blocked":
        subject = _thread_subject(prompt_text or assistant_text)
        return {
            "thread_key": f"blocker:{subject}:{owner}",
            "status": "blocked",
            "owner": owner,
            "summary": _truncate_text(assistant_text or prompt_text or "The current turn is blocked."),
            "next_action": "Resume the session after the blocker is cleared.",
            "unblock_condition": "Receive follow-up input or clear the blocking condition.",
        }
    if assistant_text.endswith("?"):
        subject = _thread_subject(prompt_text or assistant_text)
        return {
            "thread_key": f"user_input:{subject}:{owner}",
            "status": "waiting_user",
            "owner": owner,
            "summary": _truncate_text(assistant_text),
            "next_action": "Wait for the user to answer the outstanding question.",
            "unblock_condition": "The user provides the requested information.",
        }
    return None


def _primary_user_prompt_text(messages: tuple[RuntimeMessage, ...]) -> str:
    for message in messages:
        if message.role != MessageRole.USER or not message.text.strip():
            continue
        if any(isinstance(block, TextBlock) for block in message.content):
            return message.text.strip()
    return ""


def _thread_subject(text: str) -> str:
    normalized = normalize_memory_segment(text, default="session-thread")
    parts = [segment for segment in normalized.split("-") if segment]
    if not parts:
        return "session-thread"
    return "-".join(parts[:6])
