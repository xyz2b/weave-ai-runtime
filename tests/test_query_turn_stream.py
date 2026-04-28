import asyncio

from weavert.compaction import CompactionPolicy, CompactionResult, evaluate_context_pressure
from weavert.contracts import MessageRole, PromptContextEnvelope, RuntimePrivateContext, TextBlock, ToolResultBlock
from weavert.definitions import AgentDefinition, ToolDefinition, ToolTraits
from weavert.registries import ToolRegistry
from weavert.runtime_package_protocols import (
    CapabilityBinding,
    ContextContributorBinding,
    ContextContributorStage,
    PackageOwnership,
    RuntimeCapabilityKey,
)
from weavert.runtime_services import RuntimeServices, SidecarContributionResult
from weavert.turn_engine import (
    ContextAssembler,
    ModelRequest,
    ModelStreamEvent,
    ModelStreamEventType,
    TurnPhase,
    TurnEngine,
    TurnStreamEventType,
)


class BatchedModelClient:
    def __init__(self, event_batches: list[list[ModelStreamEvent]]) -> None:
        self._event_batches = [list(batch) for batch in event_batches]
        self.requests: list[ModelRequest] = []

    async def complete(self, request: ModelRequest):  # pragma: no cover - protocol completeness
        raise NotImplementedError

    async def stream(self, request: ModelRequest):
        self.requests.append(request)
        batch = self._event_batches.pop(0)
        for event in batch:
            yield event


class InterruptibleModelClient:
    def __init__(self) -> None:
        self.requests: list[ModelRequest] = []

    async def complete(self, request: ModelRequest):  # pragma: no cover - protocol completeness
        raise NotImplementedError

    async def stream(self, request: ModelRequest):
        self.requests.append(request)
        yield ModelStreamEvent(
            ModelStreamEventType.MESSAGE_START,
            {"request_id": "req-interrupt", "ttft_ms": 3.0},
        )
        yield ModelStreamEvent(
            ModelStreamEventType.CONTENT_BLOCK_START,
            {"block_type": "text", "text": "partial output"},
        )
        while request.abort_signal is not None and not request.abort_signal.aborted:
            await asyncio.sleep(0.01)


def test_run_turn_stream_emits_request_message_and_terminal_metadata() -> None:
    model_client = BatchedModelClient(
        [
            [
                ModelStreamEvent(
                    ModelStreamEventType.MESSAGE_START,
                    {"request_id": "req-1", "ttft_ms": 12.5},
                ),
                ModelStreamEvent(
                    ModelStreamEventType.CONTENT_BLOCK_START,
                    {"block_type": "text"},
                ),
                ModelStreamEvent(
                    ModelStreamEventType.CONTENT_BLOCK_DELTA,
                    {"block_type": "text", "text": "hello stream"},
                ),
                ModelStreamEvent(ModelStreamEventType.CONTENT_BLOCK_STOP, {"block_type": "text"}),
                ModelStreamEvent(
                    ModelStreamEventType.MESSAGE_STOP,
                    {"stop_reason": "end_turn", "usage": {"output_tokens": 5}},
                ),
            ]
        ]
    )
    engine = TurnEngine(model_client=model_client, tool_registry=ToolRegistry())
    agent = AgentDefinition(name="main-router", description="router", prompt="Answer")

    async def collect_events():
        events = []
        async for event in engine.run_turn_stream(
            session_id="session",
            turn_id="turn",
            agent=agent,
            cwd=".",
            messages=[],
            base_system_prompt="System",
            runtime_context={"query_source": "unit_test"},
        ):
            events.append(event)
        return events

    events = asyncio.run(collect_events())

    assert [event.event_type for event in events] == [
        TurnStreamEventType.REQUEST_START,
        TurnStreamEventType.STREAM_PROGRESS,
        TurnStreamEventType.STREAM_PROGRESS,
        TurnStreamEventType.STREAM_PROGRESS,
        TurnStreamEventType.STREAM_PROGRESS,
        TurnStreamEventType.STREAM_PROGRESS,
        TurnStreamEventType.MESSAGE,
        TurnStreamEventType.ATTEMPT_FINISHED,
        TurnStreamEventType.TERMINAL,
    ]
    assert events[0].request is not None
    assert events[0].request.abort_signal is not None
    assert events[0].request.query_source == "unit_test"
    assert events[-3].message is not None
    assert events[-3].message.role == MessageRole.ASSISTANT
    assert events[-3].message.text == "hello stream"
    assert events[-2].attempt is not None
    assert events[-2].attempt.stop_reason == "end_turn"
    assert events[-2].attempt.request_id == "req-1"
    assert events[-2].attempt.produced_tool_calls is False
    assert events[-2].phase == TurnPhase.STREAM_ATTEMPT
    assert events[-1].terminal is not None
    assert events[-1].terminal.request_id == "req-1"
    assert events[-1].terminal.stop_reason == "end_turn"
    assert events[-1].terminal.ttft_ms == 12.5
    assert events[-1].terminal.usage == {"output_tokens": 5}
    assert events[-1].phase == TurnPhase.TERMINAL

    result = asyncio.run(
        TurnEngine(
            model_client=BatchedModelClient(
                [
                    [
                        ModelStreamEvent(
                            ModelStreamEventType.MESSAGE_START,
                            {"request_id": "req-2", "ttft_ms": 9.0},
                        ),
                        ModelStreamEvent(
                            ModelStreamEventType.CONTENT_DELTA,
                            {"text": "aggregated"},
                        ),
                        ModelStreamEvent(
                            ModelStreamEventType.MESSAGE_STOP,
                            {"stop_reason": "end_turn", "usage": {"output_tokens": 2}},
                        ),
                    ]
                ]
            ),
            tool_registry=ToolRegistry(),
        ).run_turn(
            session_id="session",
            turn_id="turn",
            agent=agent,
            cwd=".",
            messages=[],
            base_system_prompt="System",
        )
    )
    assert result.completed is True
    assert result.messages[-1].text == "aggregated"
    assert result.stop_reason == "end_turn"
    assert result.request_id == "req-2"
    assert result.ttft_ms == 9.0
    assert result.usage == {"output_tokens": 2}
    assert result.attempts[0].request_id == "req-2"


def test_tool_continuation_emits_attempt_finished_before_unique_final_terminal() -> None:
    tool_registry = ToolRegistry()
    tool_registry.register(
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
    model_client = BatchedModelClient(
        [
            [
                ModelStreamEvent(
                    ModelStreamEventType.MESSAGE_START,
                    {"request_id": "req-tool-1"},
                ),
                ModelStreamEvent(
                    ModelStreamEventType.TOOL_CALL,
                    {"tool_name": "echo", "tool_input": {"value": "ping"}, "call_id": "call-1"},
                ),
                ModelStreamEvent(
                    ModelStreamEventType.MESSAGE_STOP,
                    {"stop_reason": "tool_use"},
                ),
            ],
            [
                ModelStreamEvent(
                    ModelStreamEventType.MESSAGE_START,
                    {"request_id": "req-tool-2"},
                ),
                ModelStreamEvent(
                    ModelStreamEventType.CONTENT_DELTA,
                    {"text": "done"},
                ),
                ModelStreamEvent(
                    ModelStreamEventType.MESSAGE_STOP,
                    {"stop_reason": "end_turn"},
                ),
            ],
        ]
    )
    engine = TurnEngine(model_client=model_client, tool_registry=tool_registry)
    agent = AgentDefinition(name="main-router", description="router", prompt="Answer", tools=("*",))

    async def collect_events():
        return [
            event
            async for event in engine.run_turn_stream(
                session_id="session",
                turn_id="turn",
                agent=agent,
                cwd=".",
                messages=[],
                base_system_prompt="System",
            )
        ]

    events = asyncio.run(collect_events())

    attempt_events = [event for event in events if event.event_type == TurnStreamEventType.ATTEMPT_FINISHED]
    terminal_events = [event for event in events if event.event_type == TurnStreamEventType.TERMINAL]

    assert len(attempt_events) == 2
    assert [event.attempt.stop_reason for event in attempt_events if event.attempt is not None] == [
        "tool_use",
        "end_turn",
    ]
    assert attempt_events[0].attempt is not None
    assert attempt_events[0].attempt.produced_tool_calls is True
    assert terminal_events[-1].terminal is not None
    assert terminal_events[-1].terminal.stop_reason == "end_turn"
    assert len(terminal_events) == 1
    assert events.index(attempt_events[0]) < events.index(terminal_events[0])
    tool_result_event = next(
        event
        for event in events
        if event.event_type == TurnStreamEventType.MESSAGE
        and event.message is not None
        and event.message.role == MessageRole.USER
    )
    assert tool_result_event.transition is not None
    assert tool_result_event.transition.reason.value == "next_turn"


def test_tool_context_exposes_turn_scoped_runtime_state() -> None:
    tool_registry = ToolRegistry()
    tool_registry.register(
        ToolDefinition(
            name="inspect_context",
            description="inspect current tool context",
            input_schema={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
            traits=ToolTraits(read_only=True, concurrency_safe=True),
            execute=lambda _tool_input, context: {
                "roles": [message.role.value for message in context.messages],
                "message_count": len(context.messages),
                "has_abort_handle": context.abort_handle is not None,
                "tool_names": [entry.name for entry in context.tool_catalog.list()],
                "has_refresh_handle": context.refresh_capabilities is not None,
                "has_private_context_view": context.private_context_view is not None,
                "has_raw_private_context": hasattr(context, "private_context"),
                "has_runtime_services": getattr(context, "runtime_services", None) is not None,
                "has_raw_tool_pool": hasattr(context, "tool_pool"),
            },
        )
    )
    model_client = BatchedModelClient(
        [
            [
                ModelStreamEvent(
                    ModelStreamEventType.MESSAGE_START,
                    {"request_id": "req-ctx-1"},
                ),
                ModelStreamEvent(
                    ModelStreamEventType.TOOL_CALL,
                    {"tool_name": "inspect_context", "tool_input": {}, "call_id": "call-ctx-1"},
                ),
                ModelStreamEvent(
                    ModelStreamEventType.MESSAGE_STOP,
                    {"stop_reason": "tool_use"},
                ),
            ],
            [
                ModelStreamEvent(
                    ModelStreamEventType.MESSAGE_START,
                    {"request_id": "req-ctx-2"},
                ),
                ModelStreamEvent(
                    ModelStreamEventType.CONTENT_DELTA,
                    {"text": "context captured"},
                ),
                ModelStreamEvent(
                    ModelStreamEventType.MESSAGE_STOP,
                    {"stop_reason": "end_turn"},
                ),
            ],
        ]
    )
    engine = TurnEngine(model_client=model_client, tool_registry=tool_registry)

    async def refresh_tools(context):
        return context.tool_pool

    engine.configure_runtime(tool_refresh_callback=refresh_tools)
    agent = AgentDefinition(name="main-router", description="router", prompt="Answer", tools=("*",))

    result = asyncio.run(
        engine.run_turn(
            session_id="session",
            turn_id="turn",
            agent=agent,
            cwd=".",
            messages=[],
            base_system_prompt="System",
        )
    )

    tool_result_message = next(
        message
        for message in result.messages
        if message.role == MessageRole.USER and any(isinstance(block, ToolResultBlock) for block in message.content)
    )
    tool_result = next(block for block in tool_result_message.content if isinstance(block, ToolResultBlock))

    assert tool_result.content["roles"] == ["assistant"]
    assert tool_result.content["message_count"] == 1
    assert tool_result.content["has_abort_handle"] is True
    assert tool_result.content["tool_names"] == ["inspect_context"]
    assert tool_result.content["has_refresh_handle"] is True
    assert tool_result.content["has_private_context_view"] is True
    assert tool_result.content["has_raw_private_context"] is False
    assert tool_result.content["has_runtime_services"] is False
    assert tool_result.content["has_raw_tool_pool"] is False
    assert result.messages[-1].text == "context captured"


def test_runtime_services_contribute_context_during_request_assembly() -> None:
    class StaticContributionService:
        def __init__(self, *lines: str) -> None:
            self._lines = lines

        async def collect(self, **kwargs):
            _ = kwargs
            return self._lines

    class StaticCompactionService(StaticContributionService):
        def __init__(self, *lines: str) -> None:
            super().__init__(*lines)
            self.calls: list[tuple[object, ...]] = []

        async def prepare_turn(self, **kwargs):
            messages = tuple(kwargs["messages"])
            self.calls.append(messages)
            policy = CompactionPolicy(enabled=False)
            return CompactionResult(
                messages=messages,
                policy=policy,
                pressure=evaluate_context_pressure(messages, policy),
                fragments=self._lines,
            )

    model_client = BatchedModelClient(
        [
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-services"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "done"}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ]
        ]
    )
    compaction_service = StaticCompactionService("Compaction line")
    services = RuntimeServices(
        memory=StaticContributionService("Memory line"),
        hooks=StaticContributionService("Hook line"),
        compaction=compaction_service,
        context_assembler=ContextAssembler(),
        metadata={"runtime_id": "unit-test"},
    )
    engine = TurnEngine(
        model_client=model_client,
        tool_registry=ToolRegistry(),
        runtime_services=services,
    )
    agent = AgentDefinition(name="main-router", description="router", prompt="Answer")

    asyncio.run(
        engine.run_turn(
            session_id="session",
            turn_id="turn",
            agent=agent,
            cwd=".",
            messages=[],
            base_system_prompt="System",
        )
    )

    request = model_client.requests[0]
    assert request.turn_context.memory_fragments == ("Memory line",)
    assert request.turn_context.hook_context == ("Hook line",)
    assert request.turn_context.compaction_fragments == ()
    assert request.turn_context.prompt_context.memory_fragments == ("Memory line",)
    assert request.metadata["runtime_id"] == "unit-test"
    assert request.metadata["control_plane"]["effect_kinds"] == []
    assert request.private_context.extensions["runtime_id"] == "unit-test"
    assert compaction_service.calls == [()]
    assert "runtime_id" not in request.system_prompt
    assert "Memory line" in request.system_prompt
    assert "Hook line" in request.system_prompt


def test_turn_engine_uses_canonical_memory_and_compaction_resolvers() -> None:
    class BrokenMemorySlot:
        pass

    class BrokenCompactionSlot:
        async def prepare_turn(self, **_kwargs):
            raise AssertionError("raw compaction slot should not be used")

    class RecordingMemoryService:
        async def collect(self, **kwargs):
            _ = kwargs
            return ("Memory via resolver",)

    class RecordingCompactionService:
        def __init__(self) -> None:
            self.calls: list[tuple[object, ...]] = []

        async def prepare_turn(self, **kwargs):
            messages = tuple(kwargs["messages"])
            self.calls.append(messages)
            policy = CompactionPolicy(enabled=False)
            return CompactionResult(
                messages=messages,
                policy=policy,
                pressure=evaluate_context_pressure(messages, policy),
            )

    class ResolverOnlyRuntimeServices(RuntimeServices):
        def __init__(self, memory_service: RecordingMemoryService, compaction_service: RecordingCompactionService):
            super().__init__(
                memory=BrokenMemorySlot(),
                compaction=BrokenCompactionSlot(),
                context_assembler=ContextAssembler(),
            )
            self._memory_service = memory_service
            self._compaction_service = compaction_service

        def resolve_memory_service(self):
            return getattr(self, "_memory_service", object.__getattribute__(self, "memory"))

        def resolve_compaction_service(self):
            return getattr(self, "_compaction_service", object.__getattribute__(self, "compaction"))

    model_client = BatchedModelClient(
        [
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-resolver-services"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "done"}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ]
        ]
    )
    memory_service = RecordingMemoryService()
    compaction_service = RecordingCompactionService()
    services = ResolverOnlyRuntimeServices(memory_service, compaction_service)
    engine = TurnEngine(
        model_client=model_client,
        tool_registry=ToolRegistry(),
        runtime_services=services,
    )
    agent = AgentDefinition(name="main-router", description="router", prompt="Answer")

    asyncio.run(
        engine.run_turn(
            session_id="session",
            turn_id="turn",
            agent=agent,
            cwd=".",
            messages=[],
            base_system_prompt="System",
        )
    )

    request = model_client.requests[0]
    assert request.turn_context.memory_fragments == ("Memory via resolver",)
    assert request.turn_context.prompt_context.memory_fragments == ("Memory via resolver",)
    assert compaction_service.calls == [()]


def test_turn_engine_context_control_plane_observes_late_compaction_rebind() -> None:
    class InitialCompactionService:
        def __init__(self) -> None:
            self.calls: list[str] = []

        async def prepare_turn(self, **kwargs):
            _ = kwargs
            self.calls.append("initial")
            policy = CompactionPolicy(enabled=False)
            return CompactionResult(
                messages=(),
                policy=policy,
                pressure=evaluate_context_pressure((), policy),
            )

    class ReplacementCompactionService:
        def __init__(self) -> None:
            self.calls: list[str] = []

        async def prepare_turn(self, **kwargs):
            _ = kwargs
            self.calls.append("replacement")
            policy = CompactionPolicy(enabled=False)
            return CompactionResult(
                messages=(),
                policy=policy,
                pressure=evaluate_context_pressure((), policy),
            )

    initial = InitialCompactionService()
    replacement = ReplacementCompactionService()
    services = RuntimeServices(
        compaction=initial,
        context_assembler=ContextAssembler(),
    )
    engine = TurnEngine(
        model_client=BatchedModelClient([]),
        tool_registry=ToolRegistry(),
        runtime_services=services,
    )
    services.bind_capability(
        CapabilityBinding(
            key=RuntimeCapabilityKey.COMPACTION_MANAGER.value,
            value=replacement,
            owner=PackageOwnership(
                package_name="weavert-compaction-override",
                package_role="capability",
                surface="capability",
            ),
        )
    )

    asyncio.run(
        engine._context_control_plane.prepare(
            session_id="session",
            turn_id="turn",
            attempt_index=0,
            agent=AgentDefinition(name="main-router", description="router", prompt="Answer"),
            cwd=".",
            messages=(),
            prompt_context=PromptContextEnvelope(),
            private_context=RuntimePrivateContext(),
            runtime_context={},
        )
    )

    assert initial.calls == []
    assert replacement.calls == ["replacement"]


def test_sidecar_private_updates_cannot_reintroduce_prompt_updates() -> None:
    class LeakyLegacySidecar:
        async def collect(self, **kwargs):
            kwargs["runtime_context"]["prompt_updates"] = {"legacy": "hidden"}
            return SidecarContributionResult(
                private_updates={"prompt_updates": {"explicit": "hidden"}, "sidecar": True}
            )

    model_client = BatchedModelClient(
        [
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-sidecar-private"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "done"}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ]
        ]
    )
    services = RuntimeServices(
        hooks=LeakyLegacySidecar(),
        context_assembler=ContextAssembler(),
    )
    engine = TurnEngine(
        model_client=model_client,
        tool_registry=ToolRegistry(),
        runtime_services=services,
    )
    agent = AgentDefinition(name="main-router", description="router", prompt="Answer")

    asyncio.run(
        engine.run_turn(
            session_id="session",
            turn_id="turn",
            agent=agent,
            cwd=".",
            messages=[],
            base_system_prompt="System",
        )
    )

    request = model_client.requests[0]
    assert request.turn_context.prompt_context.session_hints == {}
    assert "legacy: hidden" not in request.system_prompt
    assert "explicit: hidden" not in request.system_prompt
    assert request.private_context.extensions["sidecar"] is True


def test_nested_legacy_sidecar_mutations_do_not_leak_prompt_updates() -> None:
    class NestedLeakySidecar:
        async def collect(self, **kwargs):
            kwargs["runtime_context"].setdefault("prompt_updates", {})["nested"] = "hidden"
            kwargs["runtime_context"].setdefault("memory_diagnostics", {})["nested"] = "trace"
            return SidecarContributionResult(private_updates={"sidecar": True})

    model_client = BatchedModelClient(
        [
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-sidecar-nested"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "done"}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ]
        ]
    )
    services = RuntimeServices(hooks=NestedLeakySidecar(), context_assembler=ContextAssembler())
    engine = TurnEngine(
        model_client=model_client,
        tool_registry=ToolRegistry(),
        runtime_services=services,
    )
    agent = AgentDefinition(name="main-router", description="router", prompt="Answer")

    asyncio.run(
        engine.run_turn(
            session_id="session",
            turn_id="turn",
            agent=agent,
            cwd=".",
            messages=[],
            base_system_prompt="System",
            runtime_context={"prompt_updates": {"topic": "ops"}},
        )
    )

    request = model_client.requests[0]
    assert request.turn_context.prompt_context.session_hints == {"topic": "ops"}
    assert "nested: hidden" not in request.system_prompt
    assert request.private_context.extensions["sidecar"] is True
    assert request.private_context.diagnostics["memory_diagnostics"] == {"nested": "trace"}


def test_sidecar_explicit_updates_override_legacy_runtime_context_adapter() -> None:
    class MixedModeSidecar:
        async def collect(self, **kwargs):
            kwargs["runtime_context"]["sidecar"] = "compat"
            kwargs["runtime_context"]["memory_diagnostics"] = {"source": "compat"}
            return SidecarContributionResult(
                private_updates={"sidecar": "explicit"},
                diagnostics={"memory_diagnostics": {"source": "explicit"}},
            )

    model_client = BatchedModelClient(
        [
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-sidecar-precedence"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "done"}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ]
        ]
    )
    services = RuntimeServices(hooks=MixedModeSidecar(), context_assembler=ContextAssembler())
    engine = TurnEngine(
        model_client=model_client,
        tool_registry=ToolRegistry(),
        runtime_services=services,
    )
    agent = AgentDefinition(name="main-router", description="router", prompt="Answer")

    asyncio.run(
        engine.run_turn(
            session_id="session",
            turn_id="turn",
            agent=agent,
            cwd=".",
            messages=[],
            base_system_prompt="System",
        )
    )

    request = model_client.requests[0]
    assert request.private_context.extensions["sidecar"] == "explicit"


def test_authoritative_legacy_runtime_context_writes_are_blocked_by_default() -> None:
    class LegacyAuthoritySidecar:
        async def collect(self, **kwargs):
            kwargs["runtime_context"]["team_id"] = "compat-team"
            return SidecarContributionResult(private_updates={"sidecar": True})

    model_client = BatchedModelClient(
        [
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-legacy-authority"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "done"}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ]
        ]
    )
    services = RuntimeServices(hooks=LegacyAuthoritySidecar(), context_assembler=ContextAssembler())
    engine = TurnEngine(
        model_client=model_client,
        tool_registry=ToolRegistry(),
        runtime_services=services,
    )
    agent = AgentDefinition(name="main-router", description="router", prompt="Answer")

    asyncio.run(
        engine.run_turn(
            session_id="session",
            turn_id="turn",
            agent=agent,
            cwd=".",
            messages=[],
            base_system_prompt="System",
        )
    )

    request = model_client.requests[0]
    assert "team_id" not in request.private_context.extensions
    assert request.private_context.diagnostics["legacy_runtime_context_write_blocked"] == {
        "blocked_keys": ["team_id"],
        "migration_target": "RuntimePrivateContext / PromptContextEnvelope",
    }


def test_authoritative_legacy_runtime_context_writes_can_be_legacy_enabled() -> None:
    class LegacyAuthoritySidecar:
        async def collect(self, **kwargs):
            kwargs["runtime_context"]["team_id"] = "compat-team"
            return SidecarContributionResult(private_updates={"sidecar": True})

    model_client = BatchedModelClient(
        [
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-legacy-authority-enabled"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "done"}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ]
        ]
    )
    services = RuntimeServices(
        hooks=LegacyAuthoritySidecar(),
        context_assembler=ContextAssembler(),
        metadata={"legacy_compatibility": {"enabled_families": ["runtime_context_authority"]}},
    )
    engine = TurnEngine(
        model_client=model_client,
        tool_registry=ToolRegistry(),
        runtime_services=services,
    )
    agent = AgentDefinition(name="main-router", description="router", prompt="Answer")

    asyncio.run(
        engine.run_turn(
            session_id="session",
            turn_id="turn",
            agent=agent,
            cwd=".",
            messages=[],
            base_system_prompt="System",
        )
    )

    request = model_client.requests[0]
    assert request.private_context.extensions["team_id"] == "compat-team"
    assert request.private_context.extensions["sidecar"] is True
    assert "legacy_runtime_context_write_blocked" not in request.private_context.diagnostics


def test_authoritative_legacy_private_updates_are_blocked_by_default() -> None:
    class LegacyAuthoritySidecar:
        async def collect(self, **kwargs):
            return SidecarContributionResult(
                private_updates={"team_id": "compat-team", "sidecar": True}
            )

    model_client = BatchedModelClient(
        [
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-legacy-private-blocked"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "done"}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ]
        ]
    )
    services = RuntimeServices(hooks=LegacyAuthoritySidecar(), context_assembler=ContextAssembler())
    engine = TurnEngine(
        model_client=model_client,
        tool_registry=ToolRegistry(),
        runtime_services=services,
    )
    agent = AgentDefinition(name="main-router", description="router", prompt="Answer")

    asyncio.run(
        engine.run_turn(
            session_id="session",
            turn_id="turn",
            agent=agent,
            cwd=".",
            messages=[],
            base_system_prompt="System",
        )
    )

    request = model_client.requests[0]
    assert "team_id" not in request.private_context.extensions
    assert request.private_context.extensions["sidecar"] is True
    assert request.private_context.diagnostics["legacy_runtime_context_write_blocked"] == {
        "blocked_keys": ["team_id"],
        "migration_target": "RuntimePrivateContext / PromptContextEnvelope",
    }


def test_authoritative_legacy_private_updates_can_be_legacy_enabled() -> None:
    class LegacyAuthoritySidecar:
        async def collect(self, **kwargs):
            return SidecarContributionResult(
                private_updates={"team_id": "compat-team", "sidecar": True}
            )

    model_client = BatchedModelClient(
        [
            [
                ModelStreamEvent(
                    ModelStreamEventType.MESSAGE_START,
                    {"request_id": "req-legacy-private-enabled"},
                ),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "done"}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ]
        ]
    )
    services = RuntimeServices(
        hooks=LegacyAuthoritySidecar(),
        context_assembler=ContextAssembler(),
        metadata={"legacy_compatibility": {"enabled_families": ["runtime_context_authority"]}},
    )
    engine = TurnEngine(
        model_client=model_client,
        tool_registry=ToolRegistry(),
        runtime_services=services,
    )
    agent = AgentDefinition(name="main-router", description="router", prompt="Answer")

    asyncio.run(
        engine.run_turn(
            session_id="session",
            turn_id="turn",
            agent=agent,
            cwd=".",
            messages=[],
            base_system_prompt="System",
        )
    )

    request = model_client.requests[0]
    assert request.private_context.extensions["team_id"] == "compat-team"
    assert request.private_context.extensions["sidecar"] is True
    assert "legacy_runtime_context_write_blocked" not in request.private_context.diagnostics


def test_sidecar_prompt_and_private_channels_stay_separate() -> None:
    class StructuredSidecar:
        async def collect(self, **kwargs):
            prompt_context = kwargs["prompt_context"]
            private_context = kwargs["private_context"]
            assert prompt_context.session_hints == {"topic": "ops"}
            assert private_context.extensions["host_hint"] == "keep-private"
            return SidecarContributionResult(
                prompt_fragments=("Hook line",),
                private_updates={"host_hint": "still-private"},
                diagnostics={"hook_diagnostics": {"matched": True}},
            )

    model_client = BatchedModelClient(
        [
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-sidecar-split"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "done"}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ]
        ]
    )
    services = RuntimeServices(hooks=StructuredSidecar(), context_assembler=ContextAssembler())
    engine = TurnEngine(
        model_client=model_client,
        tool_registry=ToolRegistry(),
        runtime_services=services,
    )
    agent = AgentDefinition(name="main-router", description="router", prompt="Answer")

    asyncio.run(
        engine.run_turn(
            session_id="session",
            turn_id="turn",
            agent=agent,
            cwd=".",
            messages=[],
            base_system_prompt="System",
            runtime_context={
                "prompt_updates": {"topic": "ops"},
                "host_hint": "keep-private",
            },
        )
    )

    request = model_client.requests[0]
    assert "Hook line" in request.system_prompt
    assert "host_hint" not in request.system_prompt
    assert "hook_diagnostics" not in request.system_prompt
    assert request.private_context.extensions["host_hint"] == "still-private"
    assert request.private_context.diagnostics["hook_diagnostics"] == {"matched": True}


def test_package_context_contributors_execute_in_stage_order_and_merge_prompt_private_channels() -> None:
    observed: list[str] = []

    class MemoryContributor:
        async def collect(self, **kwargs):
            observed.append("memory")
            assert kwargs["prompt_context"].memory_fragments == ()
            return SidecarContributionResult(
                prompt_fragments=("Memory line",),
                private_updates={"memory_private": True},
            )

    class HookEarlyContributor:
        async def collect(self, **kwargs):
            observed.append("hook-early")
            assert kwargs["prompt_context"].memory_fragments == ("Memory line",)
            return SidecarContributionResult(
                prompt_fragments=("Hook early",),
                private_updates={"hook_order": "early"},
            )

    class HookLateContributor:
        async def collect(self, **kwargs):
            observed.append("hook-late")
            assert kwargs["prompt_context"].hook_fragments == ("Hook early",)
            return SidecarContributionResult(
                prompt_fragments=("Hook late",),
                private_updates={"hook_order": "late"},
            )

    class TaskPolicyContributor:
        async def collect(self, **kwargs):
            observed.append("task-policy")
            assert kwargs["prompt_context"].hook_fragments == ("Hook early", "Hook late")
            return SidecarContributionResult(
                prompt_fragments=("Task reminder",),
                private_updates={"private_only": "kept"},
            )

    model_client = BatchedModelClient(
        [
            [
                ModelStreamEvent(
                    ModelStreamEventType.MESSAGE_START,
                    {"request_id": "req-package-context-order"},
                ),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "done"}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ]
        ]
    )
    services = RuntimeServices(context_assembler=ContextAssembler())
    owner = PackageOwnership(package_name="runtime-test", package_role="capability", surface="context_contributor")
    services.register_context_contributor(
        ContextContributorBinding(
            name="runtime-test.memory",
            stage=ContextContributorStage.MEMORY,
            contributor=MemoryContributor(),
            owner=owner,
        )
    )
    services.register_context_contributor(
        ContextContributorBinding(
            name="runtime-test.hook-early",
            stage=ContextContributorStage.HOOKS,
            contributor=HookEarlyContributor(),
            owner=owner,
            order=10,
        )
    )
    services.register_context_contributor(
        ContextContributorBinding(
            name="runtime-test.hook-late",
            stage=ContextContributorStage.HOOKS,
            contributor=HookLateContributor(),
            owner=owner,
            order=20,
        )
    )
    services.register_context_contributor(
        ContextContributorBinding(
            name="runtime-test.task-policy",
            stage=ContextContributorStage.TASK_POLICY,
            contributor=TaskPolicyContributor(),
            owner=owner,
        )
    )
    engine = TurnEngine(
        model_client=model_client,
        tool_registry=ToolRegistry(),
        runtime_services=services,
    )
    agent = AgentDefinition(name="main-router", description="router", prompt="Answer")

    asyncio.run(
        engine.run_turn(
            session_id="session",
            turn_id="turn",
            agent=agent,
            cwd=".",
            messages=[],
            base_system_prompt="System",
        )
    )

    request = model_client.requests[0]
    assert observed == ["memory", "hook-early", "hook-late", "task-policy"]
    assert request.turn_context.memory_fragments == ("Memory line",)
    assert request.turn_context.hook_context == ("Hook early", "Hook late", "Task reminder")
    assert request.private_context.extensions["memory_private"] is True
    assert request.private_context.extensions["hook_order"] == "late"
    assert request.private_context.extensions["private_only"] == "kept"


def test_package_context_contributor_failures_degrade_and_keep_private_diagnostics_hidden() -> None:
    class GoodPromptContributor:
        async def collect(self, **_kwargs):
            return ("Visible line",)

    class PrivateDiagnosticContributor:
        async def collect(self, **_kwargs):
            return SidecarContributionResult(
                private_updates={"private_flag": True},
                diagnostics={"custom_diagnostics": {"channel": "private"}},
            )

    class FailingContributor:
        async def collect(self, **_kwargs):
            raise RuntimeError("boom")

    class InvalidContributor:
        async def collect(self, **_kwargs):
            return {"bad": "shape"}

    class SlowContributor:
        async def collect(self, **_kwargs):
            await asyncio.sleep(0.02)
            return ("Too slow",)

    model_client = BatchedModelClient(
        [
            [
                ModelStreamEvent(
                    ModelStreamEventType.MESSAGE_START,
                    {"request_id": "req-package-context-failures"},
                ),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "done"}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ]
        ]
    )
    services = RuntimeServices(context_assembler=ContextAssembler())
    owner = PackageOwnership(package_name="runtime-test", package_role="capability", surface="context_contributor")
    services.register_context_contributor(
        ContextContributorBinding(
            name="runtime-test.good",
            stage=ContextContributorStage.HOOKS,
            contributor=GoodPromptContributor(),
            owner=owner,
            order=0,
        )
    )
    services.register_context_contributor(
        ContextContributorBinding(
            name="runtime-test.failing",
            stage=ContextContributorStage.HOOKS,
            contributor=FailingContributor(),
            owner=owner,
            order=10,
        )
    )
    services.register_context_contributor(
        ContextContributorBinding(
            name="runtime-test.invalid-binding",
            stage=ContextContributorStage.HOOKS,
            contributor=object(),
            owner=owner,
            order=15,
        )
    )
    services.register_context_contributor(
        ContextContributorBinding(
            name="runtime-test.invalid",
            stage=ContextContributorStage.HOOKS,
            contributor=InvalidContributor(),
            owner=owner,
            order=20,
        )
    )
    services.register_context_contributor(
        ContextContributorBinding(
            name="runtime-test.slow",
            stage=ContextContributorStage.TASK_POLICY,
            contributor=SlowContributor(),
            owner=owner,
            timeout_seconds=0.001,
        )
    )
    services.register_context_contributor(
        ContextContributorBinding(
            name="runtime-test.private",
            stage=ContextContributorStage.TASK_POLICY,
            contributor=PrivateDiagnosticContributor(),
            owner=owner,
            order=50,
        )
    )
    engine = TurnEngine(
        model_client=model_client,
        tool_registry=ToolRegistry(),
        runtime_services=services,
    )
    agent = AgentDefinition(name="main-router", description="router", prompt="Answer")

    asyncio.run(
        engine.run_turn(
            session_id="session",
            turn_id="turn",
            agent=agent,
            cwd=".",
            messages=[],
            base_system_prompt="System",
        )
    )

    request = model_client.requests[0]
    assert "Visible line" in request.system_prompt
    assert "custom_diagnostics" not in request.system_prompt
    assert "private_flag" not in request.system_prompt
    assert "Too slow" not in request.system_prompt
    assert request.private_context.extensions["private_flag"] is True
    assert request.private_context.diagnostics["custom_diagnostics"] == {"channel": "private"}
    diagnostics = request.private_context.diagnostics["context_contributor_diagnostics"]
    assert {entry["code"] for entry in diagnostics} == {
        "context_contributor_failed",
        "context_contributor_invalid_binding",
        "context_contributor_invalid_output",
        "context_contributor_timeout",
    }
    assert {entry["contributor"] for entry in diagnostics} == {
        "runtime-test.failing",
        "runtime-test.invalid-binding",
        "runtime-test.invalid",
        "runtime-test.slow",
    }
    assert {entry["owner"]["package_name"] for entry in diagnostics} == {"runtime-test"}


def test_explicit_context_carriers_override_legacy_runtime_context_inputs() -> None:
    observed: list[dict[str, object]] = []

    class InspectingSidecar:
        async def collect(self, **kwargs):
            observed.append(kwargs)
            return SidecarContributionResult()

    model_client = BatchedModelClient(
        [
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-explicit-context"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "done"}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ]
        ]
    )
    services = RuntimeServices(hooks=InspectingSidecar(), context_assembler=ContextAssembler())
    engine = TurnEngine(
        model_client=model_client,
        tool_registry=ToolRegistry(),
        runtime_services=services,
    )
    agent = AgentDefinition(name="main-router", description="router", prompt="Answer")

    asyncio.run(
        engine.run_turn(
            session_id="session",
            turn_id="turn",
            agent=agent,
            cwd=".",
            messages=[],
            base_system_prompt="System",
            prompt_context=PromptContextEnvelope(
                session_hints={"topic": "explicit"},
                compaction_continuation={"cursor": "explicit"},
            ),
            private_context=RuntimePrivateContext(extensions={"host_hint": "explicit"}),
            runtime_context={
                "prompt_updates": {"topic": "legacy"},
                "compaction_continuation": {"cursor": "legacy"},
                "host_hint": "legacy",
            },
        )
    )

    sidecar_call = observed[0]
    assert sidecar_call["prompt_context"].session_hints == {"topic": "explicit"}
    assert sidecar_call["prompt_context"].compaction_continuation == {"cursor": "explicit"}
    assert sidecar_call["private_context"].extensions["host_hint"] == "explicit"
    assert sidecar_call["runtime_context"]["prompt_updates"] == {"topic": "explicit"}
    assert sidecar_call["runtime_context"]["compaction_continuation"] == {"cursor": "explicit"}


def test_interrupt_aborts_model_stream_and_discards_partial_output() -> None:
    model_client = InterruptibleModelClient()
    engine = TurnEngine(model_client=model_client, tool_registry=ToolRegistry())
    agent = AgentDefinition(name="main-router", description="router", prompt="Answer")

    async def collect_events():
        events = []
        async for event in engine.run_turn_stream(
            session_id="session",
            turn_id="turn",
            agent=agent,
            cwd=".",
            messages=[],
            base_system_prompt="System",
        ):
            events.append(event)
        return events

    async def scenario():
        task = asyncio.create_task(collect_events())
        while not model_client.requests:
            await asyncio.sleep(0)
        engine.interrupt("user_cancel")
        return await task

    events = asyncio.run(scenario())

    assert model_client.requests[0].abort_signal is not None
    assert model_client.requests[0].abort_signal.aborted is True
    assert model_client.requests[0].abort_signal.reason == "user_cancel"
    assert not any(event.event_type == TurnStreamEventType.MESSAGE for event in events)
    discard_event = next(event for event in events if event.event_type == TurnStreamEventType.MESSAGE_DISCARDED)
    assert discard_event.metadata["reason"] == "user_cancel"
    assert len(discard_event.discarded_content) == 1
    assert isinstance(discard_event.discarded_content[0], TextBlock)
    assert discard_event.discarded_content[0].text == "partial output"
    terminal_event = next(event for event in events if event.event_type == TurnStreamEventType.TERMINAL)
    assert terminal_event.terminal is not None
    assert terminal_event.terminal.stop_reason == "interrupted"
    assert terminal_event.terminal.abort_reason == "user_cancel"
    assert terminal_event.terminal.request_id == "req-interrupt"

    async def run_turn_with_interrupt():
        interrupting_client = InterruptibleModelClient()
        interrupting_engine = TurnEngine(model_client=interrupting_client, tool_registry=ToolRegistry())
        task = asyncio.create_task(
            interrupting_engine.run_turn(
                session_id="session",
                turn_id="turn-2",
                agent=agent,
                cwd=".",
                messages=[],
                base_system_prompt="System",
            )
        )
        while not interrupting_client.requests:
            await asyncio.sleep(0)
        interrupting_engine.interrupt("user_cancel")
        return await task

    result = asyncio.run(run_turn_with_interrupt())
    assert result.completed is False
    assert result.messages == []
    assert result.tool_calls == []
    assert result.stop_reason == "interrupted"
    assert result.abort_reason == "user_cancel"
