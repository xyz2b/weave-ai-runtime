import asyncio
import shutil
from pathlib import Path

from claude_agent_runtime.builtins.tools import builtin_tools
from claude_agent_runtime.definitions import (
    AgentDefinition,
    MemoryScope,
    PermissionBehavior,
    PermissionDecision,
)
from claude_agent_runtime.memory import MemoryManager, MemoryManagerService
from claude_agent_runtime.registries import AgentRegistry, ToolRegistry
from claude_agent_runtime.runtime_kernel import BuiltinPackConfig, RuntimeConfig, assemble_runtime
from claude_agent_runtime.runtime_services import RuntimeServices
from claude_agent_runtime.session_runtime import InMemoryTranscriptStore, InboundEvent, InboundEventType, SessionController
from claude_agent_runtime.tasking import TaskManager
from claude_agent_runtime.tool_runtime import ToolCall, ToolCallStatus, ToolContext, ToolScheduler
from claude_agent_runtime.turn_engine import (
    ContextAssembler,
    ModelRequest,
    ModelStreamEvent,
    ModelStreamEventType,
    TurnEngine,
)


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


def test_memory_manager_resolves_user_project_and_local_scopes(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    workspace = project_root / "workspace"
    workspace.mkdir(parents=True)
    user_root = tmp_path / "user-home" / ".claude"

    manager = MemoryManager(project_root=project_root, user_root=user_root)
    default_agent = AgentDefinition(name="main-router", description="router", prompt="route")
    user_agent = AgentDefinition(
        name="user-memory",
        description="user memory",
        prompt="route",
        memory=MemoryScope.USER,
    )
    local_agent = AgentDefinition(
        name="local-memory",
        description="local memory",
        prompt="route",
        memory=MemoryScope.LOCAL,
    )

    project_context = manager.resolve_context(session_id="session", agent=default_agent, cwd=workspace)
    user_context = manager.resolve_context(session_id="session", agent=user_agent, cwd=workspace)
    local_context = manager.resolve_context(session_id="session", agent=local_agent, cwd=workspace)

    assert project_context.scope == MemoryScope.PROJECT
    assert project_context.entrypoint_path == project_root / ".claude" / "memory" / "MEMORY.md"
    assert user_context.scope == MemoryScope.USER
    assert user_context.entrypoint_path == user_root / "memory" / "MEMORY.md"
    assert local_context.scope == MemoryScope.LOCAL
    assert local_context.entrypoint_path == workspace / ".claude" / "memory" / "MEMORY.md"


def test_session_start_loads_memory_entrypoint_and_retrieves_relevant_documents(tmp_path: Path) -> None:
    project_root = _load_claude_memory_fixture(tmp_path)
    model_client = FakeModelClient(
        [
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-memory-1"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "done"}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ]
        ]
    )
    services = RuntimeServices(
        memory=MemoryManagerService(project_root=project_root),
        context_assembler=ContextAssembler(),
    )
    agent = AgentDefinition(name="main-router", description="router", prompt="route")
    controller = SessionController(
        session_id="session-memory",
        agent=agent,
        turn_engine=TurnEngine(
            model_client=model_client,
            tool_registry=ToolRegistry(),
            runtime_services=services,
        ),
        transcript_store=InMemoryTranscriptStore(),
        cwd=str(project_root),
        system_prompt="System",
        runtime_services=services,
    )

    asyncio.run(controller.start())
    resolved = services.memory.resolve_context(
        session_id="session-memory",
        agent=agent,
        cwd=project_root,
    )
    assert resolved.entrypoint_path.exists()

    controller.enqueue_event(
        InboundEvent(
            InboundEventType.USER_PROMPT,
            "How do I run pytest in this repo?",
        )
    )
    asyncio.run(controller.run_until_idle())

    fragments = model_client.requests[0].turn_context.memory_fragments
    assert any("Use pytest via `pytest -q`." in fragment for fragment in fragments)
    assert any("The project uses pytest for unit tests" in fragment for fragment in fragments)


def test_main_thread_memory_extraction_persists_and_surfaces_on_next_turn(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    model_client = FakeModelClient(
        [
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-memory-2a"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "Noted"}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ],
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-memory-2b"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "Reminder"}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ],
        ]
    )
    services = RuntimeServices(
        memory=MemoryManagerService(project_root=project_root),
        context_assembler=ContextAssembler(),
    )
    agent = AgentDefinition(name="main-router", description="router", prompt="route")
    controller = SessionController(
        session_id="session-memory-extract",
        agent=agent,
        turn_engine=TurnEngine(
            model_client=model_client,
            tool_registry=ToolRegistry(),
            runtime_services=services,
        ),
        transcript_store=InMemoryTranscriptStore(),
        cwd=str(project_root),
        system_prompt="System",
        runtime_services=services,
    )

    asyncio.run(controller.start())
    controller.enqueue_event(
        InboundEvent(
            InboundEventType.USER_PROMPT,
            "Remember that the project uses pytest and I prefer concise answers.",
        )
    )
    asyncio.run(controller.run_until_idle())

    documents = sorted((project_root / ".claude" / "memory" / "documents").glob("*.md"))
    assert len(documents) == 1
    assert "The project uses pytest and I prefer concise answers" in documents[0].read_text(encoding="utf-8")
    notifications = controller.runtime_services.host.current_notifications()
    assert notifications[-1].metadata["memory_update"] is True

    controller.enqueue_event(
        InboundEvent(
            InboundEventType.USER_PROMPT,
            "How should I run pytest here?",
        )
    )
    asyncio.run(controller.run_until_idle())

    fragments = model_client.requests[1].turn_context.memory_fragments
    assert any(
        "The project uses pytest and I prefer concise answers" in fragment
        for fragment in fragments
    )


def test_builtin_file_tools_exclude_reserved_memory_paths(tmp_path: Path) -> None:
    project_root = _load_claude_memory_fixture(tmp_path)
    (project_root / "README.md").write_text("Run pytest from the repo root.\n", encoding="utf-8")

    tool_registry = ToolRegistry()
    for definition in builtin_tools():
        tool_registry.register(definition)

    agent_registry = AgentRegistry()
    agent_registry.register(AgentDefinition(name="main-router", description="router", prompt="route"))

    async def permission_handler(*args, **kwargs) -> PermissionDecision:
        _ = args, kwargs
        return PermissionDecision(PermissionBehavior.ALLOW)

    context = ToolContext(
        session_id="session-tools",
        turn_id="turn-tools",
        agent_name="main-router",
        cwd=project_root,
        tool_registry=tool_registry,
        agent_registry=agent_registry,
        task_manager=TaskManager(),
        permission_handler=permission_handler,
        runtime_services=RuntimeServices(memory=MemoryManagerService(project_root=project_root)),
    )
    scheduler = ToolScheduler(tool_registry)

    results = asyncio.run(
        scheduler.run(
            [
                ToolCall("1", "read", {"file_path": ".claude/memory/MEMORY.md"}),
                ToolCall(
                    "2",
                    "edit",
                    {
                        "file_path": ".claude/memory/MEMORY.md",
                        "old_string": "pytest",
                        "new_string": "nose",
                    },
                ),
                ToolCall("3", "write", {"file_path": ".claude/memory/notes.md", "content": "blocked"}),
                ToolCall("4", "glob", {"pattern": "**/*.md", "root": "."}),
                ToolCall("5", "grep", {"pattern": "pytest", "path": "."}),
            ],
            context,
        )
    )

    assert results[0].status == ToolCallStatus.ERROR
    assert "reserved for runtime memory" in (results[0].error or "")
    assert results[1].status == ToolCallStatus.ERROR
    assert "reserved for runtime memory" in (results[1].error or "")
    assert results[2].status == ToolCallStatus.ERROR
    assert "reserved for runtime memory" in (results[2].error or "")
    assert results[3].status == ToolCallStatus.SUCCESS
    assert results[3].output["matches"] == [str((project_root / "README.md").resolve())]
    assert results[4].status == ToolCallStatus.SUCCESS
    assert all(".claude/memory" not in match["file_path"] for match in results[4].output["matches"])
    assert results[4].output["matches"][0]["file_path"] == str((project_root / "README.md").resolve())


def test_delegated_agent_uses_explicit_project_memory_scope(tmp_path: Path) -> None:
    project_root = _load_claude_memory_fixture(tmp_path)
    workspace = project_root / "workspace"
    model_client = FakeModelClient(
        [
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-main-1"}),
                ModelStreamEvent(
                    ModelStreamEventType.TOOL_CALL,
                    {
                        "tool_name": "agent",
                        "tool_input": {"agent": "worker", "prompt": "check the memory scope"},
                        "call_id": "call-memory-agent",
                    },
                ),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "tool_use"}),
            ],
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-worker"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "worker complete"}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ],
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-main-2"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "done"}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ],
        ]
    )
    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=project_root,
            model_client=model_client,
            builtins=BuiltinPackConfig(
                agent_replacements={
                    "main-router": AgentDefinition(
                        name="main-router",
                        description="router",
                        prompt="route",
                        tools=("*",),
                        memory=MemoryScope.LOCAL,
                    )
                },
                extra_agents=[
                    AgentDefinition(
                        name="worker",
                        description="worker",
                        prompt="work",
                        tools=("*",),
                        memory=MemoryScope.PROJECT,
                    )
                ],
            ),
        )
    )

    asyncio.run(runtime.run_prompt("Delegate this turn", session_id="session-delegate", cwd=workspace))

    main_fragments = model_client.requests[0].turn_context.memory_fragments
    worker_fragments = model_client.requests[1].turn_context.memory_fragments

    assert any("temporary refactor notes" in fragment for fragment in main_fragments)
    assert any("temporary refactor notes" in fragment for fragment in worker_fragments)
    assert not any("Use pytest via `pytest -q`." in fragment for fragment in worker_fragments)


def _load_claude_memory_fixture(tmp_path: Path) -> Path:
    project_root = tmp_path / "project"
    shutil.copytree(_fixture_root(), project_root, dirs_exist_ok=True)
    return project_root


def _fixture_root() -> Path:
    return Path(__file__).resolve().parent / "fixtures" / "memory" / "claude_style" / "project"
