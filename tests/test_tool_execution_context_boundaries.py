import asyncio
from pathlib import Path
from typing import Any

from runtime.contracts import MessageRole, RuntimeMessage, ToolResultBlock
from runtime.definitions import (
    AgentDefinition,
    DefinitionOrigin,
    DefinitionSource,
    ToolDefinition,
    ToolTraits,
)
from runtime.registries import ToolRegistry
from runtime.runtime_services import RuntimeServices
from runtime.session_runtime import (
    FileTranscriptStore,
    InboundEvent,
    InboundEventType,
    SessionController,
)
from runtime.tool_lifecycle import AppStateSet
from runtime.tool_runtime import ToolCall, ToolContext, ToolScheduler
from runtime.turn_engine import ModelStreamEvent, ModelStreamEventType, TurnEngine


class BatchedModelClient:
    def __init__(self, event_batches: list[list[ModelStreamEvent]]) -> None:
        self._event_batches = [list(batch) for batch in event_batches]

    async def complete(self, request):  # pragma: no cover - protocol completeness
        raise NotImplementedError

    async def stream(self, request):
        _ = request
        batch = self._event_batches.pop(0)
        for event in batch:
            yield event


def test_session_scope_persists_across_turns_while_turn_scope_resets(tmp_path: Path) -> None:
    registry = ToolRegistry()

    async def scope_probe(_: dict[str, Any], context) -> dict[str, Any]:
        prior_session = context.session_state.get("scope", "seen")
        prior_turn = context.turn_state.get("scope", "seen")
        prior_observed_paths = len(context.file_state.observed_paths())
        context.session_state.set("scope", "seen", (prior_session or 0) + 1)
        context.turn_state.set("scope", "seen", (prior_turn or 0) + 1)
        context.file_state.record_read(str((Path(context.cwd) / "note.txt").resolve()))
        return {
            "prior_session": prior_session,
            "prior_turn": prior_turn,
            "prior_observed_paths": prior_observed_paths,
        }

    registry.register(
        ToolDefinition(
            name="scope_probe",
            description="inspect scope lifetimes",
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
            traits=ToolTraits(read_only=True, concurrency_safe=True),
            origin=DefinitionOrigin(DefinitionSource.USER),
            execute=scope_probe,
        )
    )

    client = BatchedModelClient(
        [
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-1a"}),
                ModelStreamEvent(
                    ModelStreamEventType.TOOL_CALL,
                    {"tool_name": "scope_probe", "tool_input": {}, "call_id": "call-1"},
                ),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "tool_use"}),
            ],
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-1b"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "first done"}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ],
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-2a"}),
                ModelStreamEvent(
                    ModelStreamEventType.TOOL_CALL,
                    {"tool_name": "scope_probe", "tool_input": {}, "call_id": "call-2"},
                ),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "tool_use"}),
            ],
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-2b"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "second done"}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ],
        ]
    )
    controller = SessionController(
        session_id="session-boundaries",
        agent=AgentDefinition(name="main-router", description="router", prompt="route", tools=("*",)),
        turn_engine=TurnEngine(model_client=client, tool_registry=registry),
        transcript_store=FileTranscriptStore(tmp_path / "transcripts"),
        cwd=str(tmp_path),
        system_prompt="System",
    )

    async def run_turn(prompt: str) -> tuple[RuntimeMessage, ...]:
        controller.enqueue_event(InboundEvent(InboundEventType.USER_PROMPT, prompt))
        return await controller.run_until_idle()

    first_messages = asyncio.run(run_turn("first"))
    second_messages = asyncio.run(run_turn("second"))

    first_tool_result = next(
        block
        for message in first_messages
        if message.role == MessageRole.USER
        for block in message.content
        if isinstance(block, ToolResultBlock)
    )
    second_tool_result = next(
        block
        for message in second_messages
        if message.role == MessageRole.USER
        for block in message.content
        if isinstance(block, ToolResultBlock)
    )

    assert first_tool_result.content == {
        "prior_session": None,
        "prior_turn": None,
        "prior_observed_paths": 0,
    }
    assert second_tool_result.content == {
        "prior_session": 1,
        "prior_turn": None,
        "prior_observed_paths": 0,
    }


def test_public_tool_execution_context_is_narrowed_by_default(tmp_path: Path) -> None:
    registry = ToolRegistry()
    definition = ToolDefinition(
        name="inspect_public_context",
        description="inspect the public execution surface",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        traits=ToolTraits(read_only=True, concurrency_safe=True),
        origin=DefinitionOrigin(DefinitionSource.USER),
        execute=lambda _tool_input, context: {
            "has_runtime_services": getattr(context, "runtime_services", None) is not None,
            "has_raw_tool_pool": hasattr(context, "tool_pool"),
            "has_raw_private_context": hasattr(context, "private_context"),
            "has_private_context_view": context.private_context_view is not None,
            "tool_names": [entry.name for entry in context.tool_catalog.list()],
        },
    )
    registry.register(definition)
    context = ToolContext(
        session_id="session-public",
        turn_id="turn-public",
        agent_name="main-router",
        cwd=tmp_path,
        tool_registry=registry,
        tool_pool=(definition,),
        runtime_services=RuntimeServices(),
    )

    result = asyncio.run(
        ToolScheduler(registry).run(
            [ToolCall("call-public", "inspect_public_context", {})],
            context,
        )
    )[0]

    assert result.status.value == "success"
    assert result.output == {
        "has_runtime_services": False,
        "has_raw_tool_pool": False,
        "has_raw_private_context": False,
        "has_private_context_view": True,
        "tool_names": ["inspect_public_context"],
    }


def test_legacy_and_privileged_routes_keep_internal_tool_context(tmp_path: Path) -> None:
    registry = ToolRegistry()
    legacy = ToolDefinition(
        name="legacy_probe",
        description="legacy compat probe",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        runtime_execution_class="legacy-compat",
        execute=lambda _tool_input, context: {
            "has_runtime_services": context.runtime_services is not None,
            "has_call_updates": hasattr(context, "call_updates"),
            "call_updates_len": len(context.call_updates),
        },
    )
    privileged = ToolDefinition(
        name="privileged_probe",
        description="privileged probe",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        runtime_execution_class="privileged",
        execute=lambda _tool_input, context: {
            "has_runtime_services": context.runtime_services is not None,
            "has_agent_runner": context.agent_runner is not None,
        },
    )
    registry.register(legacy)
    registry.register(privileged)

    async def agent_runner(*args, **kwargs) -> dict[str, Any]:
        _ = args, kwargs
        return {"ok": True}

    context = ToolContext(
        session_id="session-internal",
        turn_id="turn-internal",
        agent_name="main-router",
        cwd=tmp_path,
        tool_registry=registry,
        tool_pool=(legacy, privileged),
        runtime_services=RuntimeServices(),
        agent_runner=agent_runner,
    )

    async def run() -> tuple[Any, Any]:
        scheduler = ToolScheduler(registry)
        legacy_result = await scheduler.run([ToolCall("call-legacy", "legacy_probe", {})], context)
        privileged_result = await scheduler.run(
            [ToolCall("call-privileged", "privileged_probe", {})],
            context,
        )
        return legacy_result[0], privileged_result[0]

    legacy_result, privileged_result = asyncio.run(run())

    assert legacy_result.output == {
        "has_runtime_services": True,
        "has_call_updates": True,
        "call_updates_len": 0,
    }
    assert privileged_result.output == {
        "has_runtime_services": True,
        "has_agent_runner": True,
    }


def test_non_bundled_self_declared_privilege_does_not_escalate_routing(tmp_path: Path) -> None:
    registry = ToolRegistry()
    definition = ToolDefinition(
        name="self_declared_privileged",
        description="tries to self-escalate",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        traits=ToolTraits(read_only=True, concurrency_safe=True),
        runtime_execution_class="privileged",
        metadata={"runtime_execution_class": "privileged"},
        origin=DefinitionOrigin(DefinitionSource.USER),
        execute=lambda _tool_input, context: {
            "has_runtime_services": getattr(context, "runtime_services", None) is not None,
            "has_raw_tool_pool": hasattr(context, "tool_pool"),
            "has_private_context_view": context.private_context_view is not None,
        },
    )
    registry.register(definition)
    context = ToolContext(
        session_id="session-authority",
        turn_id="turn-authority",
        agent_name="main-router",
        cwd=tmp_path,
        tool_registry=registry,
        tool_pool=(definition,),
        runtime_services=RuntimeServices(),
    )

    result = asyncio.run(
        ToolScheduler(registry).run(
            [ToolCall("call-authority", "self_declared_privileged", {})],
            context,
        )
    )[0]

    assert result.output == {
        "has_runtime_services": False,
        "has_raw_tool_pool": False,
        "has_private_context_view": True,
    }

