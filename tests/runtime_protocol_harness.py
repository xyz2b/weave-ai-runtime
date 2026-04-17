from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Sequence

from claude_agent_runtime.contracts import RuntimeMessage, serialize_content_blocks
from claude_agent_runtime.definitions import (
    AgentDefinition,
    IsolationMode,
    SkillDefinition,
    SkillExecutionContext,
    ToolDefinition,
    ToolTraits,
)
from claude_agent_runtime.registries import ToolRegistry
from claude_agent_runtime.runtime_kernel import BuiltinPackConfig, RuntimeAssembly, RuntimeConfig, assemble_runtime
from claude_agent_runtime.session_runtime import SessionController
from claude_agent_runtime.turn_engine import (
    ModelRequest,
    ModelStreamEvent,
    TranscriptEntry,
    TranscriptStore,
    TurnEngine,
    TurnStreamEvent,
)

_EPHEMERAL_KEYS = frozenset({"message_id"})


class RequestCaptureModelClient:
    def __init__(self, event_batches: Sequence[Sequence[ModelStreamEvent]]) -> None:
        self._event_batches = [list(batch) for batch in event_batches]
        self.requests: list[ModelRequest] = []

    async def complete(self, request: ModelRequest):  # pragma: no cover - protocol completeness
        raise NotImplementedError

    async def stream(self, request: ModelRequest):
        self.requests.append(request)
        if not self._event_batches:
            raise AssertionError("Received more model requests than scripted event batches")
        for event in self._event_batches.pop(0):
            yield event


class InterruptibleCaptureModelClient:
    def __init__(self, prefix_events: Sequence[ModelStreamEvent]) -> None:
        self._prefix_events = list(prefix_events)
        self.requests: list[ModelRequest] = []

    async def complete(self, request: ModelRequest):  # pragma: no cover - protocol completeness
        raise NotImplementedError

    async def stream(self, request: ModelRequest):
        self.requests.append(request)
        for event in self._prefix_events:
            yield event
        while request.abort_signal is not None and not request.abort_signal.aborted:
            await asyncio.sleep(0)


def make_main_router_agent(*, tools: Sequence[str] = (), max_turns: int | None = None) -> AgentDefinition:
    return AgentDefinition(
        name="main-router",
        description="router",
        prompt="Route the turn",
        tools=tuple(tools),
        max_turns=max_turns,
    )


def build_echo_tool_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="echo",
            description="echo values",
            input_schema={
                "type": "object",
                "properties": {"value": {"type": "string"}},
                "required": ["value"],
                "additionalProperties": False,
            },
            traits=ToolTraits(read_only=True, concurrency_safe=True),
            execute=lambda tool_input, _: {"echo": tool_input["value"]},
        )
    )
    return registry


def message_fixture(message: RuntimeMessage) -> dict[str, Any]:
    fixture: dict[str, Any] = {
        "role": message.role.value,
        "content": _normalize_fixture_value(serialize_content_blocks(message.content)),
    }
    if message.metadata:
        fixture["metadata"] = _normalize_fixture_value(message.metadata)
    return fixture


def messages_fixture(messages: Sequence[RuntimeMessage]) -> list[dict[str, Any]]:
    return [message_fixture(message) for message in messages]


def request_fixture(request: ModelRequest) -> dict[str, Any]:
    fixture: dict[str, Any] = {
        "messages": messages_fixture(request.messages),
    }
    if request.query_source is not None:
        fixture["query_source"] = request.query_source
    return fixture


def request_messages_fixture(request: ModelRequest) -> list[dict[str, Any]]:
    return request_fixture(request)["messages"]


def turn_event_fixture(event: TurnStreamEvent) -> dict[str, Any]:
    fixture: dict[str, Any] = {
        "type": event.event_type.value,
        "iteration": event.iteration,
    }
    if event.event_type.value == "request_start" and event.request is not None:
        fixture["request"] = request_fixture(event.request)
    if event.message is not None:
        fixture["message"] = message_fixture(event.message)
    if event.discarded_content:
        fixture["discarded"] = _normalize_fixture_value(serialize_content_blocks(event.discarded_content))
    if event.attempt is not None:
        attempt: dict[str, Any] = {}
        if event.attempt.stop_reason is not None:
            attempt["stop_reason"] = event.attempt.stop_reason
        if event.attempt.request_id is not None:
            attempt["request_id"] = event.attempt.request_id
        if event.attempt.ttft_ms is not None:
            attempt["ttft_ms"] = event.attempt.ttft_ms
        if event.attempt.abort_reason is not None:
            attempt["abort_reason"] = event.attempt.abort_reason
        if event.attempt.error is not None:
            attempt["error"] = event.attempt.error
        if event.attempt.usage:
            attempt["usage"] = _normalize_fixture_value(event.attempt.usage)
        if event.attempt.produced_tool_calls:
            attempt["produced_tool_calls"] = True
        if event.attempt.tool_call_count:
            attempt["tool_call_count"] = event.attempt.tool_call_count
        if event.attempt.metadata:
            attempt["metadata"] = _normalize_fixture_value(event.attempt.metadata)
        if attempt:
            fixture["attempt"] = attempt
    if event.terminal is not None:
        terminal: dict[str, Any] = {}
        if event.terminal.stop_reason is not None:
            terminal["stop_reason"] = event.terminal.stop_reason
        provider_stop_reason = getattr(event.terminal, "provider_stop_reason", None)
        if provider_stop_reason is not None and provider_stop_reason != event.terminal.stop_reason:
            terminal["provider_stop_reason"] = provider_stop_reason
        if event.terminal.request_id is not None:
            terminal["request_id"] = event.terminal.request_id
        if event.terminal.ttft_ms is not None:
            terminal["ttft_ms"] = event.terminal.ttft_ms
        if event.terminal.abort_reason is not None:
            terminal["abort_reason"] = event.terminal.abort_reason
        if event.terminal.error is not None:
            terminal["error"] = event.terminal.error
        if event.terminal.usage:
            terminal["usage"] = _normalize_fixture_value(event.terminal.usage)
        if event.terminal.metadata:
            terminal["metadata"] = _normalize_fixture_value(event.terminal.metadata)
        if terminal:
            fixture["terminal"] = terminal
    if event.metadata:
        fixture["metadata"] = _normalize_fixture_value(event.metadata)
    return fixture


def turn_events_fixture(events: Sequence[TurnStreamEvent]) -> list[dict[str, Any]]:
    return [turn_event_fixture(event) for event in events]


def capture_turn_events(engine: TurnEngine, **kwargs: Any) -> tuple[TurnStreamEvent, ...]:
    async def _collect() -> tuple[TurnStreamEvent, ...]:
        return tuple([event async for event in engine.run_turn_stream(**kwargs)])

    return asyncio.run(_collect())


def capture_session_events(controller: SessionController) -> tuple[TurnStreamEvent, ...]:
    async def _collect() -> tuple[TurnStreamEvent, ...]:
        return tuple([event async for event in controller.stream_until_idle()])

    return asyncio.run(_collect())


def capture_runtime_events(
    runtime: RuntimeAssembly,
    prompt: str,
    *,
    session_id: str,
    agent_name: str | None = None,
) -> tuple[TurnStreamEvent, ...]:
    async def _collect() -> tuple[TurnStreamEvent, ...]:
        return tuple(
            [
                event
                async for event in runtime.stream_prompt(
                    prompt,
                    session_id=session_id,
                    agent_name=agent_name,
                )
            ]
        )

    return asyncio.run(_collect())


def append_transcript_messages(
    store: TranscriptStore,
    *,
    session_id: str,
    messages: Sequence[RuntimeMessage],
    turn_id: str = "seed-turn",
) -> None:
    async def _append() -> None:
        for message in messages:
            await store.append(
                TranscriptEntry(
                    session_id=session_id,
                    turn_id=turn_id,
                    message=message,
                )
            )

    asyncio.run(_append())


def build_builtin_orchestration_runtime(
    tmp_path: Path,
    *,
    event_batches: Sequence[Sequence[ModelStreamEvent]],
    transcript_store: TranscriptStore | None = None,
) -> tuple[RuntimeAssembly, RequestCaptureModelClient]:
    model_client = RequestCaptureModelClient(event_batches)
    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            model_client=model_client,
            transcript_store=transcript_store,
            builtins=BuiltinPackConfig(
                extra_agents=[
                    AgentDefinition(
                        name="verification",
                        description="verify",
                        prompt="verify",
                        tools=("*",),
                        isolation=IsolationMode.WORKTREE,
                    ),
                    AgentDefinition(
                        name="general-purpose",
                        description="general",
                        prompt="general",
                        tools=("*",),
                    ),
                ],
                extra_skills=[
                    SkillDefinition(
                        name="fork-skill",
                        description="fork",
                        content="Forked skill ${ARG1}",
                        execution_context=SkillExecutionContext.FORK,
                        agent="general-purpose",
                    )
                ],
            ),
        )
    )
    return runtime, model_client


def _normalize_fixture_value(value: Any) -> Any:
    if isinstance(value, dict):
        normalized: dict[str, Any] = {}
        for key, inner in value.items():
            key_text = str(key)
            if key_text in _EPHEMERAL_KEYS:
                continue
            normalized[key_text] = _normalize_fixture_value(inner)
        return normalized
    if isinstance(value, tuple):
        return [_normalize_fixture_value(inner) for inner in value]
    if isinstance(value, list):
        return [_normalize_fixture_value(inner) for inner in value]
    return value
