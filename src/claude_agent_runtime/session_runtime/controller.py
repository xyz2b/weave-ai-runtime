from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import AsyncIterator
from uuid import uuid4

from ..contracts import MessageRole, RuntimeMessage, SessionCommand, SessionCommandType, SessionState, SessionStatus
from ..definitions import AgentDefinition, PermissionMode
from ..hooks import SessionEndPayload, SessionStartPayload
from ..permissions import PermissionContext
from ..runtime_services import DefaultTranscriptService, RuntimeServices
from ..turn_engine.engine import TurnEngine, TurnStreamEvent, TurnStreamEventType
from ..turn_engine.models import TranscriptEntry, TranscriptStore


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
    def runtime_services(self) -> RuntimeServices:
        return self._runtime_services

    async def start(self) -> None:
        if not self._started:
            await self._runtime_services.host.startup()
            await self._runtime_services.host.ready()
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
            message = RuntimeMessage(
                message_id=uuid4().hex,
                role=_role_for_command(command.command_type),
                content=str(command.payload["content"]),
                metadata=command.payload.get("metadata", {}),
            )
            await self._record_message(
                message,
                turn_id=self.state.active_turn_id,
            )
            async for event in self._turn_engine.run_turn_stream(
                session_id=self.state.session_id,
                turn_id=self.state.active_turn_id,
                agent=self._agent,
                cwd=self._cwd,
                messages=list(self._messages),
                base_system_prompt=self._system_prompt,
                runtime_context={
                    "command_type": command.command_type.value,
                    "permission_context": self.state.metadata.get("permission_context"),
                },
            ):
                if event.event_type == TurnStreamEventType.MESSAGE and event.message is not None:
                    await self._record_message(
                        event.message,
                        turn_id=self.state.active_turn_id,
                    )
                await self._runtime_services.host.emit_turn_event(self.state.session_id, event)
                if (
                    event.event_type == TurnStreamEventType.TERMINAL
                    and event.terminal is not None
                    and event.terminal.stop_reason == "blocked"
                ):
                    self.state.status = SessionStatus.WAITING
                yield event
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


def _role_for_command(command_type: SessionCommandType) -> MessageRole:
    if command_type == SessionCommandType.SYSTEM_MESSAGE:
        return MessageRole.SYSTEM
    if command_type == SessionCommandType.TASK_NOTIFICATION:
        return MessageRole.NOTIFICATION
    return MessageRole.USER
