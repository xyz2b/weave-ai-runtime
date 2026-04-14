from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from uuid import uuid4

from ..contracts import MessageRole, RuntimeMessage, SessionCommand, SessionCommandType, SessionState, SessionStatus
from ..definitions import AgentDefinition
from ..turn_engine.engine import TurnEngine
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
    ) -> None:
        self.state = SessionState(session_id=session_id, current_agent=agent.name)
        self._agent = agent
        self._turn_engine = turn_engine
        self._transcript_store = transcript_store
        self._cwd = cwd
        self._system_prompt = system_prompt
        self._messages: list[RuntimeMessage] = []

    @property
    def messages(self) -> tuple[RuntimeMessage, ...]:
        return tuple(self._messages)

    async def start(self) -> None:
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

    async def run_until_idle(self) -> tuple[RuntimeMessage, ...]:
        if self.state.status == SessionStatus.IDLE:
            await self.start()

        produced: list[RuntimeMessage] = []
        while self.state.queued_commands:
            command = self.state.queued_commands.pop(0)
            message = RuntimeMessage(
                message_id=uuid4().hex,
                role=_role_for_command(command.command_type),
                content=str(command.payload["content"]),
                metadata=command.payload.get("metadata", {}),
            )
            self._messages.append(message)
            await self._transcript_store.append(
                TranscriptEntry(
                    session_id=self.state.session_id,
                    turn_id=self.state.active_turn_id,
                    message=message,
                )
            )
            self.state.status = SessionStatus.RUNNING
            self.state.active_turn_id = uuid4().hex
            turn_result = await self._turn_engine.run_turn(
                session_id=self.state.session_id,
                turn_id=self.state.active_turn_id,
                agent=self._agent,
                cwd=self._cwd,
                messages=list(self._messages),
                base_system_prompt=self._system_prompt,
                runtime_context={"command_type": command.command_type.value},
            )
            for output in turn_result.messages:
                self._messages.append(output)
                produced.append(output)
                await self._transcript_store.append(
                    TranscriptEntry(
                        session_id=self.state.session_id,
                        turn_id=self.state.active_turn_id,
                        message=output,
                    )
                )
            self.state.active_turn_id = None
            if self.state.status != SessionStatus.INTERRUPTED:
                self.state.status = SessionStatus.READY

        return tuple(produced)


def _role_for_command(command_type: SessionCommandType) -> MessageRole:
    if command_type == SessionCommandType.SYSTEM_MESSAGE:
        return MessageRole.SYSTEM
    if command_type == SessionCommandType.TASK_NOTIFICATION:
        return MessageRole.NOTIFICATION
    return MessageRole.USER
