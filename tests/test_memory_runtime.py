import asyncio
import json
import shutil
from dataclasses import replace
from pathlib import Path

from claude_agent_runtime.builtins.tools import builtin_tools
from claude_agent_runtime.contracts import MessageRole, RuntimeMessage
from claude_agent_runtime.definitions import (
    AgentDefinition,
    MemoryScope,
    PermissionBehavior,
    PermissionDecision,
)
from claude_agent_runtime.execution_policy import build_root_execution_policy, resolve_agent_execution_policy
from claude_agent_runtime.hooks import RuntimeHookPhase
from claude_agent_runtime.memory import MemoryEntry, MemoryManager, MemoryManagerService
from claude_agent_runtime.permissions import PermissionContext
from claude_agent_runtime.registries import AgentRegistry, ToolRegistry
from claude_agent_runtime.runtime_kernel import BuiltinPackConfig, RuntimeConfig, assemble_runtime
from claude_agent_runtime.runtime_services import RuntimeServices
from claude_agent_runtime.session_runtime import (
    InMemoryTranscriptStore,
    InboundEvent,
    InboundEventType,
    SessionController,
    SessionStatus,
)
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
    assert resolved.long_term_manifest_path.exists()
    assert resolved.agent_manifest_path.exists()

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
    trace = model_client.requests[0].turn_context.metadata["memory_retrieval"]
    assert "memory_retrieval" not in model_client.requests[0].system_prompt
    assert trace["applied_filters"] == (
        "manifest_header_prefilter",
        "lexical_shortlist",
        "hard_filter+boost+decay",
    )
    assert trace["budget_decisions"][1]["layer"] == "shared_long_term"


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
            "Remember that the project uses pytest. I prefer concise answers.",
        )
    )
    asyncio.run(controller.run_until_idle())

    preference_documents = sorted((project_root / ".claude" / "memory" / "documents" / "preferences").glob("*.md"))
    convention_documents = sorted((project_root / ".claude" / "memory" / "documents" / "conventions").glob("*.md"))
    assert len(preference_documents) == 1
    assert len(convention_documents) == 1
    assert "memory_kind: preference" in preference_documents[0].read_text(encoding="utf-8")
    assert "I prefer concise answers" in preference_documents[0].read_text(encoding="utf-8")
    assert "memory_kind: project_convention" in convention_documents[0].read_text(encoding="utf-8")
    assert "The project uses pytest" in convention_documents[0].read_text(encoding="utf-8")

    manifest_payload = json.loads(
        (project_root / ".claude" / "memory" / "manifests" / "long-term-manifest.json").read_text(encoding="utf-8")
    )
    assert manifest_payload["schema_version"] == "memory.v2"
    assert manifest_payload["manifest_kind"] == "long_term"
    assert manifest_payload["stats"]["entry_count"] == 2
    assert {entry["memory_kind"] for entry in manifest_payload["entries"]} == {"preference", "project_convention"}
    notifications = controller.runtime_services.host.current_notifications()
    assert notifications[-1].metadata["memory_update"] is True
    assert len(notifications[-1].metadata["memory_write_receipts"]) == 2

    controller.enqueue_event(
        InboundEvent(
            InboundEventType.USER_PROMPT,
            "How should I run pytest here?",
        )
    )
    asyncio.run(controller.run_until_idle())

    fragments = model_client.requests[1].turn_context.memory_fragments
    assert any("The project uses pytest" in fragment for fragment in fragments)


def test_record_turn_with_receipts_routes_fact_taxonomy_to_shared_agent_session_and_drop(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    manager = MemoryManager(project_root=project_root)
    agent = AgentDefinition(name="main-router", description="router", prompt="route")
    manager.initialize_session(session_id="session-routing", agent=agent, cwd=project_root)

    result = manager.record_turn_with_receipts(
        session_id="session-routing",
        agent=agent,
        cwd=project_root,
        messages=(
            _user_message("msg-pref", "I prefer concise answers."),
            _user_message("msg-convention", "The project uses pytest."),
            _user_message("msg-command", "Use `pytest -q` for concise unit test runs."),
            RuntimeMessage(
                message_id="msg-agent",
                role=MessageRole.ASSISTANT,
                content="When verifying small Python changes, start with `pytest -q` before broader checks.",
            ),
            _user_message("msg-session", "We are currently debugging the memory routing issue."),
            RuntimeMessage(
                message_id="msg-thread",
                role=MessageRole.ASSISTANT,
                content="Which fixture should I use?",
            ),
            _user_message("msg-transient", "Today I need to rename the helper and move on."),
            _user_message("msg-secret", "The API token is sk-test-1234567890abcdef."),
        ),
    )

    assert len(result.persisted_documents) == 4
    persisted_kinds = {document.kind for document in result.persisted_documents}
    assert persisted_kinds == {"preference", "project_convention", "workflow_command", "agent_workflow"}
    assert any(document.path.is_relative_to(project_root / ".claude" / "memory" / "documents" / "preferences") for document in result.persisted_documents)
    assert any(document.path.is_relative_to(project_root / ".claude" / "memory" / "documents" / "conventions") for document in result.persisted_documents)
    assert any(document.path.is_relative_to(project_root / ".claude" / "memory" / "agents" / "main-router") for document in result.persisted_documents)

    receipts_by_fact = {receipt.fact_type: receipt for receipt in result.receipts}
    assert receipts_by_fact["preference"].action == "persisted"
    assert receipts_by_fact["project_convention"].action == "persisted"
    assert receipts_by_fact["workflow_command"].action == "persisted"
    assert receipts_by_fact["agent_workflow"].action == "persisted"
    assert receipts_by_fact["session_continuity"].action == "session_routed"
    assert receipts_by_fact["session_continuity"].target_layer == "session_summary"
    assert receipts_by_fact["session_thread"].action == "session_routed"
    assert receipts_by_fact["session_thread"].target_layer == "session_open_threads"
    assert receipts_by_fact["transient_task"].action == "dropped"
    assert receipts_by_fact["transient_task"].reason == "transient_task"
    assert receipts_by_fact["sensitive_value"].action == "dropped"
    assert receipts_by_fact["sensitive_value"].reason == "sensitive_value"


def test_memory_update_owned_skips_automatic_extraction(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    model_client = FakeModelClient(
        [
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-memory-owned"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "Acknowledged"}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ]
        ]
    )
    services = RuntimeServices(
        memory=MemoryManagerService(project_root=project_root),
        context_assembler=ContextAssembler(),
    )
    controller = SessionController(
        session_id="session-memory-owned",
        agent=AgentDefinition(name="main-router", description="router", prompt="route"),
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
            "I prefer concise answers.",
            metadata={"memory_update_owned": True},
        )
    )
    asyncio.run(controller.run_until_idle())

    documents_root = project_root / ".claude" / "memory" / "documents"
    assert list(documents_root.rglob("*.md")) == []
    assert controller.state.metadata.get("memory_write_receipts") in (None, [])


def test_memory_start_initializes_layered_layout_and_agent_manifest(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    manager = MemoryManager(project_root=project_root)
    agent = AgentDefinition(name="main-router", description="router", prompt="route")

    context = manager.initialize_session(
        session_id="session-layout",
        agent=agent,
        cwd=project_root,
    )

    assert context.shared_documents_dir.exists()
    assert context.preferences_documents_dir.exists()
    assert context.agents_dir.exists()
    assert context.sessions_dir.exists()
    assert context.consolidations_dir.exists()
    assert context.long_term_manifest_path.exists()
    assert context.agent_manifest_path.exists()
    assert context.session_manifest_path.exists()
    assert context.consolidation_manifest_path.exists()

    agent_manifest = json.loads(context.agent_manifest_path.read_text(encoding="utf-8"))
    assert agent_manifest["schema_version"] == "memory.v2"
    assert agent_manifest["manifest_kind"] == "agent"
    assert agent_manifest["namespaces"] == []


def test_invalid_frontmatter_memory_artifact_degrades_without_breaking_retrieval(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    documents_dir = project_root / ".claude" / "memory" / "documents" / "shared"
    documents_dir.mkdir(parents=True)
    _write_v2_memory_artifact(
        documents_dir / "valid-pytest.md",
        title="Pytest Workflow",
        content="Use pytest -q for concise unit test runs.",
        scope="project",
    )
    (documents_dir / "broken.md").write_text(
        "---\nmemory_kind: preference\nscope: project\ntags: [broken\n---\n# Broken\n\ninvalid\n",
        encoding="utf-8",
    )

    manager = MemoryManager(project_root=project_root)
    agent = AgentDefinition(name="main-router", description="router", prompt="route")
    manager.initialize_session(session_id="session-invalid", agent=agent, cwd=project_root)

    fragments, trace = manager.collect_with_trace(
        session_id="session-invalid",
        turn_id="turn-invalid",
        agent=agent,
        cwd=project_root,
        messages=(
            _user_message("msg-invalid", "How do I run pytest in this repo?"),
        ),
    )

    assert any("Use pytest -q for concise unit test runs." in fragment for fragment in fragments)
    assert trace["budget_decisions"][1]["layer"] == "shared_long_term"

    manifest_payload = json.loads(
        (project_root / ".claude" / "memory" / "manifests" / "long-term-manifest.json").read_text(encoding="utf-8")
    )
    assert manifest_payload["stats"]["entry_count"] == 1
    assert manifest_payload["stats"]["invalid_entry_count"] == 1


def test_layered_retrieval_prioritizes_agent_namespace_shared_long_term_and_session_summary(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    memory_root = project_root / ".claude" / "memory"
    _write_v2_memory_artifact(
        memory_root / "documents" / "shared" / "pytest-shared.md",
        title="Shared Pytest Workflow",
        content="Use pytest -q from the repository root.",
        scope="project",
    )
    (memory_root / "agents" / "main-router" / "documents" / "heuristics").mkdir(parents=True)
    (memory_root / "agents" / "main-router" / "documents" / "heuristics" / "pytest-heuristic.md").write_text(
        "# Pytest Heuristic\n\nCheck pytest -q first before broader verification.\n",
        encoding="utf-8",
    )
    session_dir = memory_root / "sessions" / "session-layered"
    session_dir.mkdir(parents=True)
    (session_dir / "session-summary.md").write_text(
        "# Session Summary\n\nWe are actively debugging pytest failures in this repo.\n",
        encoding="utf-8",
    )

    service = MemoryManagerService(project_root=project_root)
    agent = AgentDefinition(name="main-router", description="router", prompt="route")
    runtime_context: dict[str, object] = {}
    asyncio.run(
        service.start_session(
            session_id="session-layered",
            agent=agent,
            cwd=project_root,
        )
    )

    fragments = asyncio.run(
        service.collect(
            session_id="session-layered",
            turn_id="turn-layered",
            agent=agent,
            cwd=str(project_root),
            messages=(_user_message("msg-layered", "How should I run pytest here?"),),
            runtime_context=runtime_context,
        )
    )

    assert "Pytest Heuristic" in fragments[0]
    assert "Shared Pytest Workflow" in fragments[1]
    assert "Session Summary" in fragments[2]

    trace = runtime_context["memory_retrieval"]
    assert trace["budget_decisions"][0]["layer"] == "agent_namespace"
    assert trace["budget_decisions"][1]["layer"] == "shared_long_term"
    assert trace["budget_decisions"][2]["layer"] == "session_summary"
    assert trace["selected_doc_ids"][0] == "agents/main-router/documents/heuristics/pytest-heuristic.md"

    agent_manifest = json.loads(
        (project_root / ".claude" / "memory" / "manifests" / "agent-manifest.json").read_text(encoding="utf-8")
    )
    assert agent_manifest["namespaces"][0]["agent_name"] == "main-router"
    assert agent_manifest["namespaces"][0]["entry_count"] == 1


def test_agent_namespace_retrieval_prefers_query_match_over_path_order(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    memory_root = project_root / ".claude" / "memory"
    agent_docs = memory_root / "agents" / "main-router" / "documents" / "heuristics"
    agent_docs.mkdir(parents=True)
    (agent_docs / "aaa-build.md").write_text(
        "# Build Heuristic\n\nRun npm build for release checks.\n",
        encoding="utf-8",
    )
    (agent_docs / "zzz-pytest.md").write_text(
        "# Pytest Heuristic\n\nRun pytest -q first for small Python changes.\n",
        encoding="utf-8",
    )

    manager = MemoryManager(project_root=project_root)
    agent = AgentDefinition(name="main-router", description="router", prompt="route")
    manager.initialize_session(session_id="session-agent-query", agent=agent, cwd=project_root)

    fragments, trace = manager.collect_with_trace(
        session_id="session-agent-query",
        turn_id="turn-agent-query",
        agent=agent,
        cwd=project_root,
        messages=(_user_message("msg-agent-query", "How should I run pytest here?"),),
    )

    assert "Pytest Heuristic" in fragments[0]
    assert "Build Heuristic" not in fragments[0]
    assert trace["selected_doc_ids"][0] == "agents/main-router/documents/heuristics/zzz-pytest.md"


def test_scope_mismatched_long_term_artifact_is_excluded_from_manifest(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    misplaced = project_root / ".claude" / "memory" / "documents" / "shared" / "misplaced.md"
    _write_v2_memory_artifact(
        misplaced,
        title="Misplaced Scope",
        content="This file lives in project memory but claims user scope.",
        scope="user",
    )

    manager = MemoryManager(project_root=project_root)
    agent = AgentDefinition(name="main-router", description="router", prompt="route")
    context = manager.initialize_session(session_id="session-misplaced", agent=agent, cwd=project_root)

    manifest_payload = json.loads(context.long_term_manifest_path.read_text(encoding="utf-8"))
    assert manifest_payload["stats"]["entry_count"] == 0
    assert manifest_payload["stats"]["invalid_entry_count"] == 1


def test_agent_namespace_manifest_ignores_invalid_docs_and_non_string_conflict_keys(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    namespace_root = project_root / ".claude" / "memory" / "agents" / "main-router"
    _write_v2_memory_artifact(
        namespace_root / "documents" / "heuristics" / "valid.md",
        title="Valid Namespace Note",
        content="Use pytest -q first.",
        scope="project",
        namespace="agent:main-router",
        agent_namespace="main-router",
    )
    (namespace_root / "documents" / "heuristics" / "broken.md").write_text(
        "---\nmemory_kind: note\nscope: project\ntags: [broken\n---\n# Broken\n\ninvalid\n",
        encoding="utf-8",
    )
    namespace_root.mkdir(parents=True, exist_ok=True)
    (namespace_root / "namespace-manifest.json").write_text(
        json.dumps({"entries": [{"conflict_key": "a"}, {"conflict_key": ""}, {"conflict_key": 123}]}, indent=2) + "\n",
        encoding="utf-8",
    )

    manager = MemoryManager(project_root=project_root)
    agent = AgentDefinition(name="main-router", description="router", prompt="route")
    context = manager.initialize_session(session_id="session-agent-manifest", agent=agent, cwd=project_root)

    manifest_payload = json.loads(context.agent_manifest_path.read_text(encoding="utf-8"))
    namespace = manifest_payload["namespaces"][0]
    assert namespace["entry_count"] == 1
    assert namespace["conflict_keys"] == ["a"]


def test_agent_namespace_document_must_match_its_namespace_path(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    namespace_root = project_root / ".claude" / "memory" / "agents" / "main-router" / "documents" / "heuristics"
    _write_v2_memory_artifact(
        namespace_root / "wrong-agent.md",
        title="Wrong Namespace",
        content="This file lives under main-router but claims another agent namespace.",
        scope="project",
        namespace="agent:other-agent",
        agent_namespace="other-agent",
    )

    manager = MemoryManager(project_root=project_root)
    agent = AgentDefinition(name="main-router", description="router", prompt="route")
    context = manager.initialize_session(session_id="session-wrong-agent", agent=agent, cwd=project_root)

    agent_manifest = json.loads(context.agent_manifest_path.read_text(encoding="utf-8"))
    assert agent_manifest["namespaces"][0]["entry_count"] == 0

    fragments, _ = manager.collect_with_trace(
        session_id="session-wrong-agent",
        turn_id="turn-wrong-agent",
        agent=agent,
        cwd=project_root,
        messages=(_user_message("msg-wrong-agent", "How should I run pytest?"),),
    )
    assert not any("Wrong Namespace" in fragment for fragment in fragments)


def test_agent_namespace_durable_writes_refresh_namespace_manifest(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    manager = MemoryManager(project_root=project_root)
    agent = AgentDefinition(name="main-router", description="router", prompt="route")
    manager.initialize_session(session_id="session-agent-write", agent=agent, cwd=project_root)

    persisted = manager.persist_agent_namespace_entries(
        session_id="session-agent-write",
        agent=agent,
        cwd=project_root,
        entries=(
            MemoryEntry(
                title="Pytest Heuristic",
                content="Run pytest -q first for targeted verification.",
                metadata={
                    "memory_kind": "agent_workflow",
                    "tags": ["testing", "heuristic"],
                    "conflict_key": "agent_workflow.main-router.python-tests",
                },
            ),
        ),
    )

    assert len(persisted) == 1
    path = persisted[0].path
    assert path.parent == project_root / ".claude" / "memory" / "agents" / "main-router" / "documents" / "heuristics"
    raw_document = path.read_text(encoding="utf-8")
    assert "namespace: agent:main-router" in raw_document
    assert "agent_namespace: main-router" in raw_document

    namespace_manifest = json.loads(
        (project_root / ".claude" / "memory" / "agents" / "main-router" / "namespace-manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert namespace_manifest["manifest_kind"] == "agent_namespace"
    assert namespace_manifest["agent_name"] == "main-router"
    assert namespace_manifest["stats"]["entry_count"] == 1
    assert namespace_manifest["entries"][0]["path"].startswith("agents/main-router/documents/heuristics/")
    assert namespace_manifest["entries"][0]["agent_namespace"] == "main-router"

    agent_manifest = json.loads(
        (project_root / ".claude" / "memory" / "manifests" / "agent-manifest.json").read_text(encoding="utf-8")
    )
    assert agent_manifest["namespaces"][0]["agent_name"] == "main-router"
    assert agent_manifest["namespaces"][0]["entry_count"] == 1
    assert agent_manifest["namespaces"][0]["conflict_keys"] == ["agent_workflow.main-router.python-tests"]


def test_agent_namespace_durable_writes_honor_effective_scope_ceiling_and_active_namespace(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    workspace = project_root / "workspace"
    workspace.mkdir(parents=True)
    manager = MemoryManager(project_root=project_root)
    parent_agent = AgentDefinition(
        name="main-router",
        description="router",
        prompt="route",
        memory=MemoryScope.LOCAL,
    )
    worker_agent = AgentDefinition(
        name="worker",
        description="worker",
        prompt="work",
        memory=MemoryScope.PROJECT,
    )
    parent_policy = build_root_execution_policy(
        parent_agent,
        tool_pool=(),
        skill_pool=(),
        permission_context=PermissionContext(session_id="session-agent-ceiling"),
        memory_scope=parent_agent.memory,
    )
    worker_policy = resolve_agent_execution_policy(
        worker_agent,
        parent_policy=parent_policy,
        base_tool_pool=(),
        base_skill_pool=(),
        permission_context=PermissionContext(session_id="session-agent-ceiling"),
    )
    effective_worker = replace(worker_agent, memory=worker_policy.memory_scope)

    manager.initialize_session(session_id="session-agent-ceiling", agent=parent_agent, cwd=workspace)
    persisted = manager.persist_agent_namespace_entries(
        session_id="session-agent-ceiling",
        agent=effective_worker,
        cwd=workspace,
        entries=(
            MemoryEntry(
                title="Worker Note",
                content="Keep durable worker notes inside the local boundary.",
                metadata={
                    "namespace": "agent:other-agent",
                    "agent_namespace": "other-agent",
                },
            ),
        ),
    )

    assert worker_policy.memory_scope == MemoryScope.LOCAL
    assert len(persisted) == 1
    path = persisted[0].path
    assert path.is_relative_to(workspace / ".claude" / "memory" / "agents" / "worker")
    assert not path.is_relative_to(project_root / ".claude" / "memory" / "agents" / "worker")
    raw_document = path.read_text(encoding="utf-8")
    assert "namespace: agent:worker" in raw_document
    assert "agent_namespace: worker" in raw_document


def test_agent_namespace_retrieval_does_not_fallback_to_other_agent_namespaces(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    worker_docs = project_root / ".claude" / "memory" / "agents" / "worker" / "documents" / "heuristics"
    worker_docs.mkdir(parents=True)
    (worker_docs / "worker-only.md").write_text(
        "# Worker Only\n\nRun cargo test -q for Rust verification inside the worker namespace.\n",
        encoding="utf-8",
    )

    manager = MemoryManager(project_root=project_root)
    agent = AgentDefinition(name="main-router", description="router", prompt="route")
    manager.initialize_session(session_id="session-no-cross-namespace", agent=agent, cwd=project_root)

    fragments, trace = manager.collect_with_trace(
        session_id="session-no-cross-namespace",
        turn_id="turn-no-cross-namespace",
        agent=agent,
        cwd=project_root,
        messages=(_user_message("msg-no-cross-namespace", "How should I run cargo test here?"),),
    )

    assert not any("Worker Only" in fragment for fragment in fragments)
    assert trace["budget_decisions"][0]["available"] == 0


def test_agent_namespace_durable_writes_dedupe_duplicate_content(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    manager = MemoryManager(project_root=project_root)
    agent = AgentDefinition(name="main-router", description="router", prompt="route")
    manager.initialize_session(session_id="session-agent-dedupe", agent=agent, cwd=project_root)
    entry = MemoryEntry(
        title="Pytest Heuristic",
        content="Run pytest -q first for small Python changes.",
        metadata={"memory_kind": "agent_workflow"},
    )

    first_write = manager.persist_agent_namespace_entries(
        session_id="session-agent-dedupe",
        agent=agent,
        cwd=project_root,
        entries=(entry,),
    )
    second_write = manager.persist_agent_namespace_entries(
        session_id="session-agent-dedupe",
        agent=agent,
        cwd=project_root,
        entries=(entry,),
    )

    assert len(first_write) == 1
    assert second_write == ()
    documents = sorted(
        (project_root / ".claude" / "memory" / "agents" / "main-router" / "documents" / "heuristics").glob("*.md")
    )
    assert len(documents) == 1
    namespace_manifest = json.loads(
        (project_root / ".claude" / "memory" / "agents" / "main-router" / "namespace-manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert namespace_manifest["stats"]["entry_count"] == 1


def test_session_memory_artifacts_refresh_and_inject_on_follow_up_turn(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    model_client = FakeModelClient(
        [
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-session-1"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "First answer"}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ],
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-session-2"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "Second answer"}),
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
        session_id="session-summary-lifecycle",
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
    session_root = project_root / ".claude" / "memory" / "sessions" / "session-summary-lifecycle"
    assert not (session_root / "session-summary.md").exists()
    assert (session_root / "open-threads.md").exists()
    initial_metadata = json.loads((session_root / "metadata.json").read_text(encoding="utf-8"))
    assert initial_metadata["summary_version"] == 0

    controller.enqueue_event(
        InboundEvent(
            InboundEventType.USER_PROMPT,
            "Implement the session memory lifecycle and keep continuity between turns.",
        )
    )
    asyncio.run(controller.run_until_idle())

    summary_path = session_root / "session-summary.md"
    assert summary_path.exists()
    summary_text = summary_path.read_text(encoding="utf-8")
    assert "## Current Objective" in summary_text
    assert "session memory lifecycle" in summary_text
    assert "No durable session decisions recorded yet." not in summary_text

    refreshed_metadata = json.loads((session_root / "metadata.json").read_text(encoding="utf-8"))
    assert refreshed_metadata["summary_version"] == 1
    assert refreshed_metadata["last_summary_refresh_at"] is not None
    assert refreshed_metadata["open_thread_count"] == 0

    session_manifest = json.loads(
        (project_root / ".claude" / "memory" / "manifests" / "session-manifest.json").read_text(encoding="utf-8")
    )
    session_record = session_manifest["sessions"][0]
    assert session_record["session_id"] == "session-summary-lifecycle"
    assert session_record["has_summary"] is True
    assert session_record["has_open_threads"] is False
    assert session_record["open_thread_count"] == 0

    controller.enqueue_event(
        InboundEvent(
            InboundEventType.USER_PROMPT,
            "What should we keep in mind before the next step?",
        )
    )
    asyncio.run(controller.run_until_idle())

    fragments = model_client.requests[1].turn_context.memory_fragments
    assert any("Session Summary" in fragment for fragment in fragments)
    assert any("session memory lifecycle" in fragment for fragment in fragments)


def test_session_summary_refreshes_after_turn_threshold(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    model_client = FakeModelClient(
        [
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": f"req-threshold-{index}"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": f"Reply {index}"}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ]
            for index in range(1, 8)
        ]
    )
    services = RuntimeServices(
        memory=MemoryManagerService(project_root=project_root),
        context_assembler=ContextAssembler(),
    )
    agent = AgentDefinition(name="main-router", description="router", prompt="route")
    controller = SessionController(
        session_id="session-summary-threshold",
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
    for index in range(1, 8):
        controller.enqueue_event(
            InboundEvent(
                InboundEventType.USER_PROMPT,
                f"Turn {index}: continue tracking the session state.",
            )
        )
        asyncio.run(controller.run_until_idle())

    metadata = json.loads(
        (
            project_root
            / ".claude"
            / "memory"
            / "sessions"
            / "session-summary-threshold"
            / "metadata.json"
        ).read_text(encoding="utf-8")
    )
    assert metadata["summary_version"] == 2
    assert metadata["turns_since_summary"] == 0


def test_open_threads_blocked_turn_uses_stable_thread_key_and_upserts(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    model_client = FakeModelClient(
        [
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-blocked-1"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "The fixture mismatch is still blocking progress."}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ],
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-blocked-2"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "The fixture mismatch is still blocking progress."}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ],
        ]
    )
    services = RuntimeServices(
        memory=MemoryManagerService(project_root=project_root),
        context_assembler=ContextAssembler(),
    )
    services.hook_bus.register(
        session_id="session-open-threads",
        owner="host:blocker",
        phase=RuntimeHookPhase.STOP,
        handler=lambda _payload: {"continue_execution": False},
    )
    controller = SessionController(
        session_id="session-open-threads",
        agent=AgentDefinition(name="main-router", description="router", prompt="route"),
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
    for _ in range(2):
        controller.enqueue_event(
            InboundEvent(
                InboundEventType.USER_PROMPT,
                "Investigate pytest fixture mismatch.",
            )
        )
        asyncio.run(controller.run_until_idle())

    open_threads = (
        project_root / ".claude" / "memory" / "sessions" / "session-open-threads" / "open-threads.md"
    ).read_text(encoding="utf-8")
    thread_key = "blocker:investigate-pytest-fixture-mismatch:main-router"
    assert open_threads.count(f"## Thread: {thread_key}") == 1
    assert "- Status: blocked" in open_threads
    metadata = json.loads(
        (
            project_root
            / ".claude"
            / "memory"
            / "sessions"
            / "session-open-threads"
            / "metadata.json"
        ).read_text(encoding="utf-8")
    )
    assert metadata["open_thread_count"] == 1
    assert controller.state.status == SessionStatus.WAITING


def test_blocked_open_thread_surfaces_pre_turn_and_clears_after_resolution(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    model_client = FakeModelClient(
        [
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-blocked-clear-1"}),
                ModelStreamEvent(
                    ModelStreamEventType.CONTENT_DELTA,
                    {"text": "The fixture mismatch is still blocking progress."},
                ),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ],
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-blocked-clear-2"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "The fixture mismatch is fixed."}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ],
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-blocked-clear-3"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "Continue."}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ],
        ]
    )
    services = RuntimeServices(
        memory=MemoryManagerService(project_root=project_root),
        context_assembler=ContextAssembler(),
    )
    services.hook_bus.register(
        session_id="session-open-threads-clear",
        owner="host:blocker-once",
        phase=RuntimeHookPhase.STOP,
        once=True,
        handler=lambda _payload: {"continue_execution": False},
    )
    controller = SessionController(
        session_id="session-open-threads-clear",
        agent=AgentDefinition(name="main-router", description="router", prompt="route"),
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
            "Investigate pytest fixture mismatch.",
        )
    )
    asyncio.run(controller.run_until_idle())

    controller.enqueue_event(
        InboundEvent(
            InboundEventType.USER_PROMPT,
            "Investigate pytest fixture mismatch.",
        )
    )
    asyncio.run(controller.run_until_idle())

    second_fragments = model_client.requests[1].turn_context.memory_fragments
    assert any("Open Threads" in fragment for fragment in second_fragments)
    assert any("fixture mismatch is still blocking progress" in fragment for fragment in second_fragments)

    open_threads_path = project_root / ".claude" / "memory" / "sessions" / "session-open-threads-clear" / "open-threads.md"
    assert open_threads_path.read_text(encoding="utf-8") == "# Open Threads\n"
    metadata = json.loads(
        (
            project_root
            / ".claude"
            / "memory"
            / "sessions"
            / "session-open-threads-clear"
            / "metadata.json"
        ).read_text(encoding="utf-8")
    )
    assert metadata["open_thread_count"] == 0

    controller.enqueue_event(
        InboundEvent(
            InboundEventType.USER_PROMPT,
            "What should we continue with now?",
        )
    )
    asyncio.run(controller.run_until_idle())

    third_fragments = model_client.requests[2].turn_context.memory_fragments
    assert not any("Open Threads" in fragment for fragment in third_fragments)


def test_waiting_user_open_thread_surfaces_pre_turn_and_clears_after_answer(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    model_client = FakeModelClient(
        [
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-waiting-user-1"}),
                ModelStreamEvent(
                    ModelStreamEventType.CONTENT_DELTA,
                    {"text": "Which memory scope should we use for this workflow?"},
                ),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ],
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-waiting-user-2"}),
                ModelStreamEvent(
                    ModelStreamEventType.CONTENT_DELTA,
                    {"text": "Use project scope and keep the flow deterministic."},
                ),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ],
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-waiting-user-3"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "Next steps are clear."}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ],
        ]
    )
    services = RuntimeServices(
        memory=MemoryManagerService(project_root=project_root),
        context_assembler=ContextAssembler(),
    )
    controller = SessionController(
        session_id="session-waiting-user-threads",
        agent=AgentDefinition(name="main-router", description="router", prompt="route"),
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
            "Help me decide the memory scope for this workflow.",
        )
    )
    asyncio.run(controller.run_until_idle())

    controller.enqueue_event(
        InboundEvent(
            InboundEventType.USER_PROMPT,
            "Use project scope and keep the flow deterministic.",
        )
    )
    asyncio.run(controller.run_until_idle())

    second_fragments = model_client.requests[1].turn_context.memory_fragments
    assert any("Open Threads" in fragment for fragment in second_fragments)
    assert any("Which memory scope should we use" in fragment for fragment in second_fragments)

    open_threads_path = (
        project_root / ".claude" / "memory" / "sessions" / "session-waiting-user-threads" / "open-threads.md"
    )
    assert open_threads_path.read_text(encoding="utf-8") == "# Open Threads\n"
    metadata = json.loads(
        (
            project_root
            / ".claude"
            / "memory"
            / "sessions"
            / "session-waiting-user-threads"
            / "metadata.json"
        ).read_text(encoding="utf-8")
    )
    assert metadata["open_thread_count"] == 0

    controller.enqueue_event(
        InboundEvent(
            InboundEventType.USER_PROMPT,
            "What should we do next?",
        )
    )
    asyncio.run(controller.run_until_idle())

    third_fragments = model_client.requests[2].turn_context.memory_fragments
    assert not any("Open Threads" in fragment for fragment in third_fragments)


def test_session_memory_resume_preserves_summary_continuity(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    model_client = FakeModelClient(
        [
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-resume-1"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "First answer"}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ],
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-resume-2"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "Resumed answer"}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ],
        ]
    )
    services = RuntimeServices(
        memory=MemoryManagerService(project_root=project_root),
        context_assembler=ContextAssembler(),
    )
    controller = SessionController(
        session_id="session-resume-memory",
        agent=AgentDefinition(name="main-router", description="router", prompt="route"),
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
            "Keep track of this session so we can resume later.",
        )
    )
    asyncio.run(controller.run_until_idle())

    controller.interrupt()
    asyncio.run(controller.resume())
    controller.enqueue_event(
        InboundEvent(
            InboundEventType.USER_PROMPT,
            "What context should we keep after resuming?",
        )
    )
    asyncio.run(controller.run_until_idle())

    fragments = model_client.requests[1].turn_context.memory_fragments
    assert any("Session Summary" in fragment for fragment in fragments)
    assert any("Keep track of this session" in fragment for fragment in fragments)


def test_session_memory_survives_compaction_after_refresh(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    model_client = FakeModelClient(
        [
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-compaction-1"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "Initial answer"}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ],
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-compaction-2"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "Post-compaction answer"}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ],
        ]
    )
    services = RuntimeServices(
        memory=MemoryManagerService(project_root=project_root),
        context_assembler=ContextAssembler(),
    )
    controller = SessionController(
        session_id="session-compaction-memory",
        agent=AgentDefinition(name="main-router", description="router", prompt="route"),
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
            "Establish session continuity before compaction happens.",
        )
    )
    asyncio.run(controller.run_until_idle())
    asyncio.run(controller._apply_compaction(tuple(controller.messages), turn_id="turn-compaction"))

    metadata = json.loads(
        (
            project_root
            / ".claude"
            / "memory"
            / "sessions"
            / "session-compaction-memory"
            / "metadata.json"
        ).read_text(encoding="utf-8")
    )
    assert metadata["last_compaction_at"] is not None

    controller.enqueue_event(
        InboundEvent(
            InboundEventType.USER_PROMPT,
            "What should we continue with after compaction?",
        )
    )
    asyncio.run(controller.run_until_idle())

    fragments = model_client.requests[1].turn_context.memory_fragments
    assert any("Session Summary" in fragment for fragment in fragments)
    assert any("Establish session continuity before compaction happens." in fragment for fragment in fragments)


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
    (project_root / ".claude" / "memory" / "agents" / "worker" / "documents" / "heuristics").mkdir(parents=True)
    (project_root / ".claude" / "memory" / "agents" / "worker" / "documents" / "heuristics" / "project-memory.md").write_text(
        "# Worker Project Memory\n\nProject-scoped worker guidance that should stay behind the local ceiling.\n",
        encoding="utf-8",
    )
    (workspace / ".claude" / "memory" / "agents" / "main-router" / "documents" / "heuristics").mkdir(parents=True)
    (workspace / ".claude" / "memory" / "agents" / "main-router" / "documents" / "heuristics" / "local-memory.md").write_text(
        "# Main Router Local Memory\n\nMain router local heuristic for temporary refactors.\n",
        encoding="utf-8",
    )
    (workspace / ".claude" / "memory" / "agents" / "worker" / "documents" / "heuristics").mkdir(parents=True)
    (workspace / ".claude" / "memory" / "agents" / "worker" / "documents" / "heuristics" / "local-worker-memory.md").write_text(
        "# Worker Local Memory\n\nWorker-specific local guidance for delegated verification.\n",
        encoding="utf-8",
    )
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
    assert any("Main router local heuristic" in fragment for fragment in main_fragments)
    assert not any("Main router local heuristic" in fragment for fragment in worker_fragments)
    assert any("Worker-specific local guidance" in fragment for fragment in worker_fragments)
    assert not any("Worker-specific local guidance" in fragment for fragment in main_fragments)
    assert not any("Project-scoped worker guidance" in fragment for fragment in worker_fragments)
    assert not any("Use pytest via `pytest -q`." in fragment for fragment in worker_fragments)


def _load_claude_memory_fixture(tmp_path: Path) -> Path:
    project_root = tmp_path / "project"
    shutil.copytree(_fixture_root(), project_root, dirs_exist_ok=True)
    return project_root


def _fixture_root() -> Path:
    return Path(__file__).resolve().parent / "fixtures" / "memory" / "claude_style" / "project"


def _user_message(message_id: str, text: str):
    from claude_agent_runtime.contracts import MessageRole, RuntimeMessage

    return RuntimeMessage(message_id=message_id, role=MessageRole.USER, content=text)


def _write_v2_memory_artifact(
    path: Path,
    *,
    title: str,
    content: str,
    scope: str,
    namespace: str = "shared",
    agent_namespace: str | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    agent_namespace_line = "" if agent_namespace is None else f"agent_namespace: {agent_namespace}\n"
    path.write_text(
        (
            "---\n"
            "memory_kind: note\n"
            f"scope: {scope}\n"
            f"namespace: {namespace}\n"
            f"{agent_namespace_line}"
            "retention: durable_until_superseded\n"
            "source_pathway: rule\n"
            "created_at: 2026-04-17T04:00:00Z\n"
            "last_confirmed_at: 2026-04-17T04:00:00Z\n"
            "tags:\n"
            "  - testing\n"
            "---\n"
            f"# {title}\n\n"
            f"{content}\n"
        ),
        encoding="utf-8",
    )
