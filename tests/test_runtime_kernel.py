import asyncio
from pathlib import Path

from runtime.contracts import MessageRole
from runtime.hooks import RuntimeHookPhase
from runtime.definitions import (
    AgentDefinition,
    DefinitionOrigin,
    DefinitionSource,
)
from runtime.hosts.base import NullHostAdapter
from runtime.runtime_kernel import (
    BuiltinPackConfig,
    DefinitionSourcePaths,
    HostBinding,
    RuntimeConfig,
    assemble_host_runtime,
    assemble_runtime,
    build_runtime_kernel,
)
from runtime.turn_engine import ModelRequest, ModelStreamEvent, ModelStreamEventType


class FakeModelClient:
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
        yield ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-interrupt"})
        yield ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "partial"})
        while request.abort_signal is not None and not request.abort_signal.aborted:
            await asyncio.sleep(0.01)


def test_runtime_kernel_applies_builtin_switches_and_discovers_project_defs(
    tmp_path: Path,
) -> None:
    agents_dir = tmp_path / "agents"
    skills_dir = tmp_path / "skills" / "project-skill"
    agents_dir.mkdir(parents=True)
    skills_dir.mkdir(parents=True)

    (agents_dir / "main-router.md").write_text(
        """
---
name: main-router
description: project override
---
project router
""".strip(),
        encoding="utf-8",
    )
    (skills_dir / "SKILL.md").write_text(
        """
---
description: project skill
---
project skill body
""".strip(),
        encoding="utf-8",
    )

    replacement = AgentDefinition(
        name="main-router",
        description="custom builtin router",
        prompt="custom router prompt",
        origin=DefinitionOrigin(DefinitionSource.BUNDLED, path=Path("<host>")),
    )

    config = RuntimeConfig(
        working_directory=tmp_path,
        discovery_sources=(DefinitionSourcePaths(DefinitionSource.PROJECT, tmp_path),),
        builtins=BuiltinPackConfig(
            disabled_tools={"read"},
            agent_replacements={"main-router": replacement},
            disabled_skills={"debug"},
        ),
    )

    kernel = build_runtime_kernel(config)

    assert kernel.tool_registry.get("read") is None
    assert kernel.agent_registry.get("main-router") is not None
    assert kernel.agent_registry.get("main-router").description == "custom builtin router"
    assert kernel.agent_registry.get("main-router").prompt == "custom router prompt"
    assert kernel.skill_registry.get("project-skill") is not None
    assert kernel.skill_registry.get("debug") is None
    assert any(diag.code == "definition_skipped" for diag in kernel.diagnostics)


def test_host_assembly_entrypoint_binds_host(tmp_path: Path) -> None:
    def factory(name: str, config: dict[str, str], kernel: object) -> NullHostAdapter:
        assert getattr(kernel, "services", None) is not None
        _ = config, kernel
        return NullHostAdapter(name=name)

    config = RuntimeConfig(
        working_directory=tmp_path,
        host_bindings=(HostBinding(name="cli", factory=factory, config={"mode": "interactive"}),),
    )

    runtime = assemble_host_runtime(config, host_name="cli")

    assert runtime.host.name == "cli"
    assert runtime.kernel.agent_registry.get("main-router") is not None
    assert runtime.runtime is not None
    assert runtime.runtime.kernel is runtime.kernel


def test_runtime_assembly_provides_runnable_session_surface(tmp_path: Path) -> None:
    model_client = FakeModelClient(
        [
            [
                ModelStreamEvent(
                    ModelStreamEventType.MESSAGE_START,
                    {"request_id": "req-1"},
                ),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "assembled reply"}),
                ModelStreamEvent(
                    ModelStreamEventType.MESSAGE_STOP,
                    {"stop_reason": "end_turn"},
                ),
            ]
        ]
    )
    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            model_client=model_client,
            system_prompt="Assembled system prompt",
        )
    )

    produced = asyncio.run(runtime.run_prompt("Hello runtime", session_id="session-1"))
    session = runtime.create_session(session_id="session-2")

    assert produced[-1].role == MessageRole.ASSISTANT
    assert produced[-1].text == "assembled reply"
    assert runtime.services is runtime.kernel.services
    assert runtime.turn_engine.runtime_services is runtime.services
    assert runtime.agent_runtime.runtime_services is runtime.services
    assert runtime.skill_executor.runtime_services is runtime.services
    assert session.runtime_services is runtime.services
    assert runtime.transcript_store is runtime.kernel.transcript_store
    assert len(model_client.requests) == 1
    assert model_client.requests[0].query_source == "user_prompt"


def test_runtime_run_prompt_closes_helper_owned_session(tmp_path: Path) -> None:
    model_client = FakeModelClient(
        [
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-close"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "closed"}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ]
        ]
    )
    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            model_client=model_client,
        )
    )
    closed: list[str] = []
    runtime.services.hook_bus.register(
        session_id="helper-session",
        owner="test",
        phase=RuntimeHookPhase.SESSION_END,
        handler=lambda payload: closed.append(payload.final_status),
    )

    produced = asyncio.run(runtime.run_prompt("Hello runtime", session_id="helper-session"))

    assert produced[-1].text == "closed"
    assert closed == ["completed"]


def test_runtime_stream_prompt_closes_helper_owned_session_on_interrupt(tmp_path: Path) -> None:
    model_client = InterruptibleModelClient()
    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            model_client=model_client,
        )
    )
    closed: list[str] = []
    runtime.services.hook_bus.register(
        session_id="helper-stream-interrupt",
        owner="test",
        phase=RuntimeHookPhase.SESSION_END,
        handler=lambda payload: closed.append(payload.final_status),
    )

    async def scenario():
        events = []

        async def collect() -> None:
            async for event in runtime.stream_prompt(
                "Hello runtime",
                session_id="helper-stream-interrupt",
            ):
                events.append(event)

        task = asyncio.create_task(collect())
        while not model_client.requests:
            await asyncio.sleep(0)
        runtime.turn_engine.interrupt("user_cancel")
        await task
        return events

    events = asyncio.run(scenario())

    assert any(event.event_type.value == "terminal" for event in events)
    assert closed == ["interrupted"]


def test_runtime_stream_prompt_closes_helper_owned_session_on_success(tmp_path: Path) -> None:
    model_client = FakeModelClient(
        [
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-stream-ok"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "streamed"}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ]
        ]
    )
    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            model_client=model_client,
        )
    )
    closed: list[str] = []
    runtime.services.hook_bus.register(
        session_id="helper-stream-ok",
        owner="test",
        phase=RuntimeHookPhase.SESSION_END,
        handler=lambda payload: closed.append(payload.final_status),
    )

    async def scenario():
        return [
            event
            async for event in runtime.stream_prompt(
                "Hello runtime",
                session_id="helper-stream-ok",
            )
        ]

    events = asyncio.run(scenario())

    assert any(event.event_type.value == "terminal" for event in events)
    assert closed == ["completed"]


def test_runtime_stream_prompt_closes_helper_owned_session_on_blocked(tmp_path: Path) -> None:
    model_client = FakeModelClient(
        [
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-stream-blocked"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "needs approval"}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ]
        ]
    )
    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            model_client=model_client,
        )
    )
    closed: list[str] = []
    runtime.services.hook_bus.register(
        session_id="helper-stream-blocked",
        owner="test",
        phase=RuntimeHookPhase.STOP,
        handler=lambda _payload: {"stop_disposition": "block_session"},
    )
    runtime.services.hook_bus.register(
        session_id="helper-stream-blocked",
        owner="close-observer",
        phase=RuntimeHookPhase.SESSION_END,
        handler=lambda payload: closed.append(payload.final_status),
    )

    async def scenario():
        return [
            event
            async for event in runtime.stream_prompt(
                "Hello runtime",
                session_id="helper-stream-blocked",
            )
        ]

    events = asyncio.run(scenario())

    terminal = next(event for event in events if event.event_type.value == "terminal")
    assert terminal.terminal is not None
    assert terminal.terminal.stop_reason == "blocked"
    assert closed == ["stopped"]


def test_runtime_stream_prompt_closes_helper_owned_session_on_error(tmp_path: Path) -> None:
    model_client = FakeModelClient(
        [
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-error"}),
                ModelStreamEvent(ModelStreamEventType.ERROR, {"error": "model exploded"}),
            ]
        ]
    )
    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            model_client=model_client,
        )
    )
    closed: list[str] = []
    runtime.services.hook_bus.register(
        session_id="helper-stream-error",
        owner="test",
        phase=RuntimeHookPhase.SESSION_END,
        handler=lambda payload: closed.append(payload.final_status),
    )

    async def scenario():
        return [
            event
            async for event in runtime.stream_prompt(
                "Hello runtime",
                session_id="helper-stream-error",
            )
        ]

    events = asyncio.run(scenario())

    assert any(event.event_type.value == "terminal" for event in events)
    assert closed == ["failed"]
