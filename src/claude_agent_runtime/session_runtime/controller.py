from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, AsyncIterator
from uuid import uuid4

from ..compaction import latest_compaction_payload
from ..contracts import (
    MessageAttachment,
    MessageRole,
    RuntimeMessage,
    SessionCommand,
    SessionCommandType,
    SessionState,
    SessionStatus,
)
from ..definitions import AgentDefinition, PermissionMode
from ..hooks import SessionEndPayload, SessionStartPayload
from ..permissions import PermissionContext
from ..runtime_services import DefaultTranscriptService, RuntimeServices
from ..turn_engine.engine import TurnEngine, TurnStreamEvent, TurnStreamEventType
from ..turn_engine.models import TranscriptEntry, TranscriptSession, TranscriptStore


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
        self._started = False
        self.state.metadata.setdefault(
            "permission_context",
            PermissionContext(
                session_id=session_id,
                mode=agent.permission_mode or PermissionMode.DEFAULT,
            ),
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
            await self._runtime_services.host.startup()
            await self._runtime_services.host.ready()
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
        await self._runtime_services.hook_bus.dispatch(
            self.state.session_id,
            SessionEndPayload(
                session_id=self.state.session_id,
                final_status=final_status,
            ),
        )
        if self._started:
            await self._runtime_services.host.shutdown()
            self._started = False

    async def stream_until_idle(self) -> AsyncIterator[TurnStreamEvent]:
        if self.state.status == SessionStatus.IDLE:
            await self.start()

        while self.state.queued_commands:
            command = self.state.queued_commands.pop(0)
            self.state.status = SessionStatus.RUNNING
            self.state.active_turn_id = uuid4().hex
            last_terminal = None
            turn_message_ids: list[str] = []
            attachments = _coerce_attachments(command.payload.get("metadata"))
            message = RuntimeMessage(
                message_id=uuid4().hex,
                role=_role_for_command(command.command_type),
                content=str(command.payload["content"]),
                attachments=attachments,
                metadata=command.payload.get("metadata", {}),
            )
            await self._record_message(
                message,
                turn_id=self.state.active_turn_id,
            )
            turn_message_ids.append(message.message_id)
            runtime_context = {}
            if isinstance(command.payload.get("metadata"), dict):
                runtime_context.update(command.payload["metadata"])
            runtime_context.update(
                {
                    "command_type": command.command_type.value,
                    "permission_context": self.state.metadata.get("permission_context"),
                }
            )
            continuation = self.state.metadata.get("compaction_continuation")
            if isinstance(continuation, dict):
                runtime_context["compaction_continuation"] = dict(continuation)
            async for event in self._turn_engine.run_turn_stream(
                session_id=self.state.session_id,
                turn_id=self.state.active_turn_id,
                agent=self._agent,
                cwd=self._cwd,
                messages=list(self._messages),
                base_system_prompt=self._system_prompt,
                attachments=list(attachments),
                runtime_context=runtime_context,
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
                await self._runtime_services.host.emit_turn_event(self.state.session_id, event)
                if (
                    event.event_type == TurnStreamEventType.TERMINAL
                    and event.terminal is not None
                    and event.terminal.stop_reason == "blocked"
                ):
                    self.state.status = SessionStatus.WAITING
                if event.event_type == TurnStreamEventType.TERMINAL and event.terminal is not None:
                    last_terminal = event.terminal
                yield event
            current_turn_ids = set(turn_message_ids)
            turn_messages = tuple(message for message in self._messages if message.message_id in current_turn_ids)
            if (
                command.command_type == SessionCommandType.USER_PROMPT
                and self.state.status != SessionStatus.WAITING
                and not _memory_updates_owned(command.payload.get("metadata"), turn_messages)
            ):
                await self._persist_turn_memory(turn_messages, terminal=last_terminal)
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

    async def _persist_turn_memory(
        self,
        messages: tuple[RuntimeMessage, ...],
        *,
        terminal: Any,
    ) -> None:
        if terminal is None or terminal.abort_reason is not None or terminal.error is not None:
            return
        memory_service = self._runtime_services.memory
        if memory_service is None or not hasattr(memory_service, "record_turn"):
            return
        persisted = await _maybe_await(
            memory_service.record_turn(
                session_id=self.state.session_id,
                agent=self._agent,
                cwd=self._cwd,
                messages=messages,
            )
        )
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
                "memory_scope": persisted[0].scope.value,
                "memory_paths": [str(document.path) for document in persisted],
            },
        )
        await self._runtime_services.host.emit_notification(notification)

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


def _role_for_command(command_type: SessionCommandType) -> MessageRole:
    if command_type == SessionCommandType.SYSTEM_MESSAGE:
        return MessageRole.SYSTEM
    if command_type == SessionCommandType.TASK_NOTIFICATION:
        return MessageRole.NOTIFICATION
    return MessageRole.USER


def _memory_updates_owned(
    metadata: object,
    messages: tuple[RuntimeMessage, ...],
) -> bool:
    if isinstance(metadata, dict) and metadata.get("memory_update_owned"):
        return True
    return any(message.metadata.get("memory_update_owned") for message in messages)


def _coerce_attachments(metadata: object) -> tuple[MessageAttachment, ...]:
    if not isinstance(metadata, dict):
        return ()
    raw = metadata.get("attachments")
    if not isinstance(raw, list):
        return ()
    attachments: list[MessageAttachment] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        path = item.get("path")
        name = item.get("name")
        if not isinstance(path, str) or not path.strip():
            continue
        if not isinstance(name, str) or not name.strip():
            name = path.strip().split("/")[-1] or path.strip()
        mime_type = item.get("mime_type")
        attachments.append(
            MessageAttachment(
                name=name.strip(),
                path=path.strip(),
                mime_type=str(mime_type).strip() if mime_type else None,
                metadata={
                    str(key): value
                    for key, value in item.items()
                    if key not in {"name", "path", "mime_type"}
                },
            )
        )
    return tuple(attachments)


async def _maybe_await(value: Any) -> Any:
    if asyncio.iscoroutine(value):
        return await value
    return value
