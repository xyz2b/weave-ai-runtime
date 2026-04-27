from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, AsyncIterator, Mapping
from uuid import uuid4

from ..compaction import latest_compaction_payload
from ..contracts import (
    MessageAttachment,
    MessageRole,
    PromptContextEnvelope,
    RuntimeMessage,
    RuntimePrivateContext,
    coerce_request_override_state,
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
from ..hooks import (
    HookDispatchTraceQuery,
    HookInventoryQuery,
    HookRegistrationRequest,
    HookRegistrationScope,
    HookScopeLifetime,
    HookSourceKind,
    SessionEndPayload,
    SessionStartPayload,
)
from ..permissions import PermissionContext
from ..runtime_package_protocols import PackageLifecyclePhase
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
        if hasattr(self._runtime_services, "session_registry"):
            self._runtime_services.session_registry.register(self)

    @property
    def messages(self) -> tuple[RuntimeMessage, ...]:
        return tuple(self._messages)

    @property
    def cwd(self) -> str:
        return self._cwd

    @property
    def runtime_services(self) -> RuntimeServices:
        return self._runtime_services

    def current_prompt_context(self) -> PromptContextEnvelope:
        return self._session_prompt_context()

    def current_private_context(self) -> RuntimePrivateContext:
        return self._session_scope_private_context()

    def resolve_invocations(self):
        return self._turn_engine.resolve_invocation_catalog(
            session_id=self.state.session_id,
            turn_id=self.state.active_turn_id,
            cwd=self._cwd,
            messages=self.messages,
            prompt_context=self.current_prompt_context(),
            private_context=self.current_private_context(),
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

    def bind_hook_callback(self, name: str, handler: Any) -> None:
        self._runtime_services.hook_bus.bind_callback(name, handler)

    def register_hook(
        self,
        request: HookRegistrationRequest | Mapping[str, Any],
    ) -> Any:
        source_kind = HookSourceKind.SESSION_API
        if isinstance(request, HookRegistrationRequest):
            if request.scope.lifetime == HookScopeLifetime.TURN:
                source_kind = HookSourceKind.TURN_API
        elif isinstance(request, Mapping):
            raw_scope = request.get("scope")
            if isinstance(raw_scope, Mapping) and str(raw_scope.get("lifetime", "")).strip() == HookScopeLifetime.TURN.value:
                source_kind = HookSourceKind.TURN_API
        return self._runtime_services.hook_bus.register_request(
            request,
            source_kind=source_kind,
            owner=f"session:{self.state.session_id}",
            source_ref=self.state.session_id,
            session_id=self.state.session_id,
            turn_id=self.state.active_turn_id,
            default_scope_lifetime=HookScopeLifetime.SESSION,
        )

    def list_hooks(
        self,
        query: HookInventoryQuery | Mapping[str, Any] | None = None,
    ) -> tuple[Any, ...]:
        if query is None:
            query = HookInventoryQuery(session_id=self.state.session_id)
        elif isinstance(query, HookInventoryQuery) and query.session_id is None:
            query = HookInventoryQuery(
                session_id=self.state.session_id,
                turn_id=query.turn_id,
                phase=query.phase,
                owner=query.owner,
                source_kind=query.source_kind,
                limit=query.limit,
                cursor=query.cursor,
            )
        elif isinstance(query, Mapping):
            query = {"session_id": self.state.session_id, **dict(query)}
        return self._runtime_services.hook_bus.list_hooks(query)

    def list_hook_dispatch_traces(
        self,
        query: HookDispatchTraceQuery | Mapping[str, Any] | None = None,
    ) -> tuple[Any, ...]:
        if query is None:
            query = HookDispatchTraceQuery(session_id=self.state.session_id)
        elif isinstance(query, HookDispatchTraceQuery) and query.session_id is None:
            query = HookDispatchTraceQuery(
                session_id=self.state.session_id,
                turn_id=query.turn_id,
                phase=query.phase,
                owner=query.owner,
                source_kind=query.source_kind,
                limit=query.limit,
                cursor=query.cursor,
            )
        elif isinstance(query, Mapping):
            query = {"session_id": self.state.session_id, **dict(query)}
        return self._runtime_services.hook_bus.list_hook_dispatch_traces(query)

    def register_turn_hook(
        self,
        request: HookRegistrationRequest | Mapping[str, Any],
    ) -> Any:
        if isinstance(request, HookRegistrationRequest):
            request = HookRegistrationRequest(
                phase=request.phase,
                match=request.match,
                scope=HookRegistrationScope(
                    lifetime=HookScopeLifetime.TURN,
                    inherit_to_children=request.scope.inherit_to_children,
                    turn_id=request.scope.turn_id or self.state.active_turn_id,
                    session_id=self.state.session_id,
                    cleanup_boundary=request.scope.cleanup_boundary,
                ),
                handler=request.handler,
                contract=request.contract,
                owner_hint=request.owner_hint,
                source_ref=request.source_ref,
                once=request.once,
                metadata=request.metadata,
            )
        else:
            existing_scope = (
                dict(request.get("scope", {}))
                if isinstance(request.get("scope"), Mapping)
                else {}
            )
            request = {
                **dict(request),
                "scope": {
                    **existing_scope,
                    "lifetime": HookScopeLifetime.TURN.value,
                    "turn_id": self.state.active_turn_id,
                    "session_id": self.state.session_id,
                },
            }
        return self.register_hook(request)

    async def start(self) -> None:
        if hasattr(self._runtime_services, "wait_until_runtime_ready"):
            await self._runtime_services.wait_until_runtime_ready()
        replay_pending_team_messages = not self._started and not self.state.queued_commands
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
            self._call_memory_service("ensure_session_artifacts", status="active")
            self._runtime_services.hook_bus.materialize_session(self.state.session_id)
            await self._runtime_services.hook_bus.dispatch(
                self.state.session_id,
                SessionStartPayload(
                    session_id=self.state.session_id,
                    config_snapshot={
                        "agent_name": self._agent.name,
                        "cwd": self._cwd,
                    },
                ),
            )
            if hasattr(self._runtime_services, "dispatch_lifecycle_phase"):
                await self._runtime_services.dispatch_lifecycle_phase(
                    PackageLifecyclePhase.SESSION_OPEN,
                    session=self,
                )
            self._started = True
        self.state.status = SessionStatus.READY
        if replay_pending_team_messages:
            await self._replay_pending_team_messages()

    def normalize_event(self, event: InboundEvent) -> SessionCommand:
        metadata = getattr(event, "metadata", None)
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
            priority=_event_ingress_priority(metadata, fallback=priority_map[event.event_type]),
        )

    def enqueue_event(self, event: InboundEvent) -> None:
        command = self.normalize_event(event)
        self.state.queued_commands.append(command)
        self.state.queued_commands.sort(key=lambda item: (-item.priority, item.created_at))

    async def submit_runtime_event(
        self,
        event: InboundEvent,
        *,
        drain: bool = False,
    ) -> bool:
        self.enqueue_event(event)
        if self.state.status == SessionStatus.IDLE:
            await self.start()
        if not drain or self.state.status in {SessionStatus.RUNNING, SessionStatus.INTERRUPTED}:
            return False
        await self.run_until_idle()
        return True

    def interrupt(self, reason: str = "interrupt") -> None:
        self.state.status = SessionStatus.INTERRUPTED
        self._turn_engine.interrupt(reason)

    async def resume(self) -> None:
        if hasattr(self._runtime_services, "wait_until_runtime_ready"):
            await self._runtime_services.wait_until_runtime_ready()
        transcript = await self._transcript_store.load(self.state.session_id)
        self._messages = [entry.message for entry in transcript.entries]
        await self._load_persisted_session_metadata()
        self._sync_compaction_state()
        self._restore_resumable_private_context()
        _sync_skill_runtime_metadata(self.state.metadata, self._messages, self._cwd)
        if hasattr(self._runtime_services, "dispatch_lifecycle_phase"):
            await self._runtime_services.dispatch_lifecycle_phase(
                PackageLifecyclePhase.SESSION_OPEN,
                session=self,
            )
        self.state.status = SessionStatus.READY
        self.state.active_turn_id = None
        if not self.state.queued_commands:
            await self._replay_pending_team_messages()

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
            self._call_memory_service("update_session_status", status=final_status)
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
            if hasattr(self._runtime_services, "dispatch_lifecycle_phase"):
                await self._runtime_services.dispatch_lifecycle_phase(
                    PackageLifecyclePhase.SESSION_CLOSE,
                    session=self,
                    final_status=final_status,
                )
        except Exception as exc:
            error = exc
        finally:
            self._started = False
            self._closed = True
            self.state.active_turn_id = None
            self.state.status = _session_status_for_close(final_status)
            if hasattr(self._runtime_services, "session_registry"):
                self._runtime_services.session_registry.unregister(
                    self.state.session_id,
                    session=self,
                )
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
            event = self._inbound_event_from_command(command)
            ingress_result = self._ingress_processor.process(
                event,
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
            if ingress_result.private_updates:
                self._apply_ingress_private_updates(ingress_result.private_updates)
            await self._emit_ingress_replay_outputs(ingress_result.replay_outputs)
            await self._acknowledge_team_delivery(event.metadata)
            if not ingress_result.admits_turn:
                await self._persist_session_metadata()
                if self.state.status != SessionStatus.WAITING:
                    self.state.status = SessionStatus.READY
                continue

            last_terminal = None
            turn_retrieval_trace: dict[str, Any] | None = None
            turn_message_ids: list[str] = [message.message_id for message in ingress_result.normalized_messages]
            runtime_context = {
                "command_type": command.command_type.value,
                "query_source": command.command_type.value,
            }
            prompt_context = self._turn_prompt_context(ingress_result.prompt_updates)
            private_context = self._turn_private_context(ingress_result.private_updates)
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
                prompt_context=prompt_context,
                private_context=private_context,
                runtime_context=runtime_context,
                session_scope=self._session_scope,
            ):
                if event.event_type == TurnStreamEventType.COMPACTION and event.compacted_messages:
                    await self._apply_compaction(
                        event.compacted_messages,
                        turn_id=self.state.active_turn_id,
                        event_metadata=event.metadata,
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
                    self._sync_terminal_control_plane_metadata(event.terminal)
                    await self._persist_session_metadata()
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
                self._call_memory_service(
                    "refresh_session_artifacts",
                    turn_id=self.state.active_turn_id,
                    messages=turn_messages,
                    session_messages=tuple(self._messages),
                    status=(
                        "waiting"
                        if self.state.status == SessionStatus.WAITING
                        else "active"
                    ),
                    prior_status=prior_status.value,
                    terminal=last_terminal,
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
        _sync_skill_runtime_metadata(self.state.metadata, self._messages, self._cwd)
        await self._persist_session_metadata()

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

    async def _acknowledge_team_delivery(self, metadata: Mapping[str, Any] | None) -> None:
        if not isinstance(metadata, Mapping):
            return
        raw = metadata.get("team_delivery_ack")
        if not isinstance(raw, Mapping):
            return
        team_id = str(raw.get("team_id") or "").strip()
        message_id = str(raw.get("message_id") or "").strip()
        delivery_id = str(raw.get("delivery_id") or "").strip()
        if not team_id or not message_id or not delivery_id:
            return
        message_bus = (
            self._runtime_services.resolve_team_message_bus()
            if hasattr(self._runtime_services, "resolve_team_message_bus")
            else getattr(self._runtime_services, "team_message_bus", None)
        )
        if message_bus is None or not hasattr(message_bus, "acknowledge_delivery"):
            return
        await message_bus.acknowledge_delivery(
            team_id=team_id,
            message_id=message_id,
            delivery_id=delivery_id,
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

    def _session_scope_private_context(self) -> RuntimePrivateContext:
        return private_context_from_legacy_runtime_context(
            {
                **self._base_runtime_private_context(),
                "permission_context": self.state.metadata.get("permission_context"),
            }
        )

    def _session_prompt_context(self) -> PromptContextEnvelope:
        return PromptContextEnvelope(
            compaction_summary=_copy_ingress_private_value(self.state.metadata.get("compaction_summary"))
            if isinstance(self.state.metadata.get("compaction_summary"), dict)
            else None,
            compaction_boundary=_copy_ingress_private_value(self.state.metadata.get("compaction_boundary"))
            if isinstance(self.state.metadata.get("compaction_boundary"), dict)
            else None,
            compaction_continuation=(
                _copy_ingress_private_value(self.state.metadata.get("compaction_continuation"))
                if isinstance(self.state.metadata.get("compaction_continuation"), dict)
                else None
            ),
        )

    def _turn_prompt_context(
        self,
        prompt_updates: Mapping[str, Any],
    ) -> PromptContextEnvelope:
        base = self._session_prompt_context()
        session_hints = dict(base.session_hints)
        session_hints.update(
            {str(key): _copy_ingress_private_value(value) for key, value in prompt_updates.items()}
        )
        return PromptContextEnvelope(
            memory_fragments=base.memory_fragments,
            hook_fragments=base.hook_fragments,
            compaction_fragments=base.compaction_fragments,
            attachments=base.attachments,
            session_hints=session_hints,
            compaction_summary=base.compaction_summary,
            compaction_boundary=base.compaction_boundary,
            compaction_continuation=base.compaction_continuation,
            extensions=base.extensions,
        )

    def _turn_private_context(
        self,
        private_updates: Mapping[str, Any],
    ) -> RuntimePrivateContext:
        merged = self._base_runtime_private_context()
        merged.update(
            {str(key): _copy_ingress_private_value(value) for key, value in private_updates.items()}
        )
        merged["permission_context"] = self.state.metadata.get("permission_context")
        return private_context_from_legacy_runtime_context(merged)

    async def _load_persisted_session_metadata(self) -> None:
        if not hasattr(self._transcript_store, "load_session_metadata"):
            return
        persisted = await self._transcript_store.load_session_metadata(self.state.session_id)
        if not isinstance(persisted, dict):
            return
        for key, value in persisted.items():
            self.state.metadata[str(key)] = _copy_ingress_private_value(value)

    async def _persist_session_metadata(self) -> None:
        if not hasattr(self._transcript_store, "save_session_metadata"):
            return
        await self._transcript_store.save_session_metadata(
            self.state.session_id,
            _session_control_plane_metadata_snapshot(self.state.metadata),
        )

    def _restore_resumable_private_context(self) -> None:
        for key in _PERSISTED_SESSION_PRIVATE_CONTEXT_KEYS:
            value = self.state.metadata.get(key)
            if value is None:
                self._session_private_context.pop(key, None)
                continue
            self._session_private_context[key] = _copy_ingress_private_value(value)
        resumable_override = self.state.metadata.get("resumable_request_override")
        if isinstance(resumable_override, dict):
            self._session_private_context["request_override"] = _copy_ingress_private_value(
                resumable_override
            )
        else:
            self._session_private_context.pop("request_override", None)
        self._session_scope.private_context = self._session_scope_private_context()

    def _sync_terminal_control_plane_metadata(self, terminal: Any) -> None:
        metadata = getattr(terminal, "metadata", None)
        if not isinstance(metadata, dict):
            return
        control_plane = metadata.get("control_plane")
        if isinstance(control_plane, dict):
            self.state.metadata["control_plane"] = dict(control_plane)
            generation = control_plane.get("context_generation")
            if generation is not None:
                self.state.metadata["context_generation"] = generation
        resumable_override = metadata.get("resumable_request_override")
        state = coerce_request_override_state(resumable_override)
        if state is not None and state.resumable:
            self.state.metadata["resumable_request_override"] = state.serialize()
        else:
            self.state.metadata.pop("resumable_request_override", None)
        self._restore_resumable_private_context()

    async def _replay_pending_team_messages(self) -> None:
        message_bus = (
            self._runtime_services.resolve_team_message_bus()
            if hasattr(self._runtime_services, "resolve_team_message_bus")
            else getattr(self._runtime_services, "team_message_bus", None)
        )
        if message_bus is None or not hasattr(message_bus, "replay_pending_leader_messages"):
            return
        await message_bus.replay_pending_leader_messages(session_id=self.state.session_id)

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
        event_metadata: Mapping[str, Any] | None = None,
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
        if _event_has_control_plane_effect(event_metadata, "compaction"):
            self._call_memory_service("record_session_compaction")
        await self._persist_session_metadata()

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
            turn_result = type(
                "_TurnResult",
                (),
                {"persisted_documents": tuple(persisted), "receipts": ()},
            )()
        persisted_documents = tuple(getattr(turn_result, "persisted_documents", ()) or ())
        receipts = tuple(getattr(turn_result, "receipts", ()) or ())
        receipt_payloads = self._serialize_memory_receipts(receipts)
        if receipt_payloads:
            history = self.state.metadata.setdefault("memory_write_receipts", [])
            if isinstance(history, list):
                history.extend(receipt_payloads)
        self._call_memory_service(
            "record_session_memory_deltas",
            persisted=persisted_documents,
            receipts=receipts,
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
                job_service=self._runtime_services.job_service,
                team_id=self._session_team_id(),
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
                job_service=self._runtime_services.job_service,
                team_id=self._session_team_id(),
            )
        )
        return str(task_id) if task_id is not None else None

    def _resolve_session_memory_context(self) -> Any:
        memory_service = self._runtime_services.memory
        if memory_service is None or not hasattr(memory_service, "resolve_context"):
            return None
        return memory_service.resolve_context(
            session_id=self.state.session_id,
            agent=self._agent,
            cwd=self._cwd,
        )

    def _ensure_session_memory_artifacts(self, *, status: str) -> None:
        self._call_memory_service("ensure_session_artifacts", status=status)

    def _update_session_memory_status(self, status: str) -> None:
        self._call_memory_service("update_session_status", status=status)

    def _record_session_compaction(self) -> None:
        self._call_memory_service("record_session_compaction")

    def _refresh_session_memory(
        self,
        messages: tuple[RuntimeMessage, ...],
        *,
        terminal: Any,
        prior_status: SessionStatus,
    ) -> None:
        self._call_memory_service(
            "refresh_session_artifacts",
            turn_id=self.state.active_turn_id,
            messages=messages,
            session_messages=tuple(self._messages),
            status="waiting" if self.state.status == SessionStatus.WAITING else "active",
            prior_status=prior_status.value,
            terminal=terminal,
        )

    def _session_team_id(self) -> str | None:
        value = self._session_scope.private_context.extensions.get("team_id")
        normalized = str(value).strip() if value is not None else ""
        return normalized or None

    def _call_memory_service(
        self,
        method_name: str,
        /,
        *,
        include_session_context: bool = True,
        **kwargs: Any,
    ) -> Any:
        memory_service = self._runtime_services.memory
        method = getattr(memory_service, method_name, None)
        if method is None:
            return None
        payload = dict(kwargs)
        if include_session_context:
            payload = {
                "session_id": self.state.session_id,
                "agent": self._agent,
                "cwd": self._cwd,
                **payload,
            }
        return method(**payload)

    def _serialize_memory_receipts(self, receipts: tuple[Any, ...]) -> list[dict[str, object]]:
        if not receipts:
            return []
        serialized = self._call_memory_service(
            "serialize_write_receipts",
            include_session_context=False,
            receipts=receipts,
        )
        if isinstance(serialized, tuple):
            return [entry for entry in serialized if isinstance(entry, dict)]
        if isinstance(serialized, list):
            return [entry for entry in serialized if isinstance(entry, dict)]
        return []

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


def _session_control_plane_metadata_snapshot(
    metadata: Mapping[str, Any],
) -> dict[str, Any]:
    persisted: dict[str, Any] = {}
    for key in (
        "team_id",
        "team_role",
        "team_member_id",
        "team_member_name",
        "leader_session_id",
        "team_last_control_message",
        "team_last_workflow_request",
        "team_last_workflow_update",
        "team_workflow_requests",
        "compaction",
        "compaction_summary",
        "compaction_boundary",
        "compaction_continuation",
        "control_plane",
        "context_generation",
        "resumable_request_override",
    ):
        value = metadata.get(key)
        if value is None:
            continue
        persisted[key] = _copy_ingress_private_value(value)
    return persisted


_PERSISTED_SESSION_PRIVATE_CONTEXT_KEYS = (
    "team_id",
    "team_role",
    "team_member_id",
    "team_member_name",
    "leader_session_id",
    "team_last_control_message",
    "team_last_workflow_request",
    "team_last_workflow_update",
    "team_workflow_requests",
)


def _event_has_control_plane_effect(
    metadata: Mapping[str, Any] | None,
    effect_kind: str,
) -> bool:
    if not isinstance(metadata, Mapping):
        return False
    control_plane = metadata.get("control_plane")
    if not isinstance(control_plane, Mapping):
        return False
    effect_kinds = control_plane.get("effect_kinds")
    if not isinstance(effect_kinds, list):
        return False
    return effect_kind in {str(value) for value in effect_kinds}


async def _maybe_await(value: Any) -> Any:
    if asyncio.iscoroutine(value):
        return await value
    return value


def _event_ingress_priority(metadata: object, *, fallback: int) -> int:
    if not isinstance(metadata, Mapping):
        return fallback
    value = metadata.get("ingress_priority")
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _sync_skill_runtime_metadata(
    metadata: dict[str, Any],
    messages: list[RuntimeMessage],
    cwd: str,
) -> None:
    observed_paths = sorted(
        {
            str(path)
            for message in messages
            for path in _coerce_string_list(message.metadata.get("observed_paths"))
        }
    )
    if observed_paths:
        metadata["observed_paths"] = observed_paths
    dynamic_roots = _discover_dynamic_skill_roots(Path(cwd), observed_paths)
    if dynamic_roots:
        metadata["skill_dynamic_roots"] = dynamic_roots


def _coerce_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        stripped = value.strip()
        return [stripped] if stripped else []
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _discover_dynamic_skill_roots(
    session_cwd: Path,
    observed_paths: list[str],
) -> list[dict[str, Any]]:
    ledger: dict[str, dict[str, Any]] = {}
    for observed_path in observed_paths:
        resolved = _resolve_observed_path(session_cwd, observed_path)
        if resolved is None:
            continue
        cursor = resolved if resolved.is_dir() else resolved.parent
        resolved_cwd = session_cwd.resolve()
        while True:
            candidate = (cursor / ".runtime" / "skills").resolve()
            if candidate.is_dir():
                record = ledger.setdefault(
                    str(candidate),
                    {
                        "root": str(candidate),
                        "source": "project",
                        "discovered_from": [],
                    },
                )
                discovered_from = set(record["discovered_from"])
                discovered_from.add(observed_path)
                record["discovered_from"] = sorted(discovered_from)
            if cursor == resolved_cwd or resolved_cwd not in cursor.parents:
                break
            cursor = cursor.parent
    return [
        ledger[root]
        for root in sorted(ledger, key=lambda candidate: (len(Path(candidate).parts), candidate))
    ]


def _resolve_observed_path(session_cwd: Path, observed_path: str) -> Path | None:
    candidate = Path(observed_path)
    resolved = candidate.resolve() if candidate.is_absolute() else (session_cwd / candidate).resolve()
    try:
        resolved.relative_to(session_cwd.resolve())
    except ValueError:
        return None
    return resolved
