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
from claude_agent_runtime.memory import (
    MemoryEntry,
    MemoryManager,
    MemoryManagerService,
    MemoryRetrievalCandidate,
    MemoryRetrievalPolicy,
    MemoryRetrievalRankedHit,
    MemoryTurnResult,
)
from claude_agent_runtime.memory.schema import serialize_memory_artifact
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
from claude_agent_runtime.tasking import TaskManager, TaskStatus
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


class FakeEmbeddingShortlistProvider:
    def __init__(self, ranking_by_title: dict[str, float]) -> None:
        self.ranking_by_title = dict(ranking_by_title)
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    def shortlist(
        self,
        *,
        query: str,
        candidates: tuple[MemoryRetrievalCandidate, ...],
        limit: int,
    ) -> tuple[MemoryRetrievalRankedHit, ...]:
        self.calls.append((query, tuple(candidate.title for candidate in candidates)))
        ranked = [
            MemoryRetrievalRankedHit(candidate.doc_id, self.ranking_by_title[candidate.title])
            for candidate in candidates
            if candidate.title in self.ranking_by_title
        ]
        ranked.sort(key=lambda hit: -hit.score)
        return tuple(ranked[:limit])


class FakeRerankProvider:
    def __init__(self, ordered_titles: tuple[str, ...]) -> None:
        self.ordered_titles = ordered_titles
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    def rerank(
        self,
        *,
        query: str,
        candidates: tuple[MemoryRetrievalCandidate, ...],
        limit: int,
    ) -> tuple[MemoryRetrievalRankedHit, ...]:
        self.calls.append((query, tuple(candidate.title for candidate in candidates)))
        candidates_by_title = {candidate.title: candidate for candidate in candidates}
        ordered = [
            MemoryRetrievalRankedHit(candidates_by_title[title].doc_id, float(limit - index))
            for index, title in enumerate(self.ordered_titles)
            if title in candidates_by_title
        ]
        return tuple(ordered[:limit])


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


def test_turn_local_preference_like_instruction_is_dropped_as_transient_task(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    manager = MemoryManager(project_root=project_root)
    agent = AgentDefinition(name="main-router", description="router", prompt="route")
    manager.initialize_session(session_id="session-transient-preference", agent=agent, cwd=project_root)

    result = manager.record_turn_with_receipts(
        session_id="session-transient-preference",
        agent=agent,
        cwd=project_root,
        messages=(
            _user_message("msg-transient-pref-1", "I prefer to rename the helper today."),
            _user_message("msg-transient-pref-2", "Please keep responses short for this turn only."),
        ),
    )

    assert result.persisted_documents == ()
    assert len(result.receipts) == 2
    assert all(receipt.fact_type == "transient_task" for receipt in result.receipts)
    assert all(receipt.action == "dropped" for receipt in result.receipts)
    assert all(receipt.reason == "transient_task" for receipt in result.receipts)


def test_generic_control_instruction_is_not_persisted_as_workflow_command(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    manager = MemoryManager(project_root=project_root)
    agent = AgentDefinition(name="main-router", description="router", prompt="route")
    manager.initialize_session(session_id="session-generic-control", agent=agent, cwd=project_root)

    result = manager.record_turn_with_receipts(
        session_id="session-generic-control",
        agent=agent,
        cwd=project_root,
        messages=(
            _user_message("msg-control", "Use project scope and keep the flow deterministic."),
        ),
    )

    assert result.persisted_documents == ()
    assert result.receipts == ()


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


def test_agent_namespace_retrieval_skips_irrelevant_documents_without_query_match(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    memory_root = project_root / ".claude" / "memory"
    agent_docs = memory_root / "agents" / "main-router" / "documents" / "heuristics"
    agent_docs.mkdir(parents=True)
    (agent_docs / "build.md").write_text(
        "# Build Heuristic\n\nRun npm build for release checks.\n",
        encoding="utf-8",
    )

    manager = MemoryManager(project_root=project_root)
    agent = AgentDefinition(name="main-router", description="router", prompt="route")
    manager.initialize_session(session_id="session-agent-unmatched", agent=agent, cwd=project_root)

    fragments, trace = manager.collect_with_trace(
        session_id="session-agent-unmatched",
        turn_id="turn-agent-unmatched",
        agent=agent,
        cwd=project_root,
        messages=(_user_message("msg-agent-unmatched", "How should I run pytest here?"),),
    )

    assert not any("Build Heuristic" in fragment for fragment in fragments)
    assert trace["budget_decisions"][0]["layer"] == "agent_namespace"
    assert trace["budget_decisions"][0]["available"] == 1
    assert trace["budget_decisions"][0]["selected"] == 0
    assert "layer:agent_namespace" not in trace["applied_filters"]


def test_embedding_shortlist_can_add_semantic_candidate_and_report_divergence(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    memory_root = project_root / ".claude" / "memory" / "documents" / "shared"
    _write_v2_memory_artifact(
        memory_root / "backend-checklist.md",
        title="Backend Checklist",
        content="Verify service health checks before broader backend rollout.",
        scope="project",
        tags=("backend", "verification"),
    )
    _write_v2_memory_artifact(
        memory_root / "semantic-rust-checks.md",
        title="Semantic Rust Checks",
        content="Run cargo test -q before broader Rust review passes.",
        scope="project",
        tags=("rust", "compile"),
    )

    embedding_provider = FakeEmbeddingShortlistProvider({"Semantic Rust Checks": 0.95})
    manager = MemoryManager(
        project_root=project_root,
        embedding_shortlist_provider=embedding_provider,
    )
    agent = AgentDefinition(name="main-router", description="router", prompt="route")
    manager.initialize_session(session_id="session-embedding", agent=agent, cwd=project_root)

    fragments, trace = manager.collect_with_trace(
        session_id="session-embedding",
        turn_id="turn-embedding",
        agent=agent,
        cwd=project_root,
        messages=(_user_message("msg-embedding", "How should I verify service changes?"),),
    )

    assert any("Semantic Rust Checks" in fragment for fragment in fragments)
    assert "embedding_shortlist" in trace["applied_filters"]
    assert trace["lexical_doc_ids"]
    assert len(trace["embedding_doc_ids"]) == 1
    assert trace["divergence"]["detected"] is True
    assert trace["divergence"]["embedding_only"] == trace["embedding_doc_ids"]
    assert embedding_provider.calls


def test_hybrid_retrieval_keeps_embedding_candidate_when_lexical_pool_saturates(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    memory_root = project_root / ".claude" / "memory" / "documents" / "shared"
    for index in range(8):
        _write_v2_memory_artifact(
            memory_root / f"lexical-{index}.md",
            title=f"Lexical Candidate {index}",
            content=f"Verify service changes with a targeted check {index} before broader validation.",
            scope="project",
            memory_kind="workflow_command",
            tags=("verification", "service"),
        )
    _write_v2_memory_artifact(
        memory_root / "semantic-rust-checks.md",
        title="Semantic Rust Checks",
        content="Run cargo test -q before broader Rust review passes.",
        scope="project",
        memory_kind="workflow_command",
        tags=("rust", "compile"),
    )

    embedding_provider = FakeEmbeddingShortlistProvider({"Semantic Rust Checks": 0.95})
    rerank_provider = FakeRerankProvider(("Semantic Rust Checks", "Lexical Candidate 0"))
    manager = MemoryManager(
        project_root=project_root,
        retrieval_policy=MemoryRetrievalPolicy(embedding_score_weight=0.0),
        embedding_shortlist_provider=embedding_provider,
        rerank_provider=rerank_provider,
    )
    agent = AgentDefinition(name="main-router", description="router", prompt="route")
    manager.initialize_session(session_id="session-embedding-saturated", agent=agent, cwd=project_root)

    fragments, trace = manager.collect_with_trace(
        session_id="session-embedding-saturated",
        turn_id="turn-embedding-saturated",
        agent=agent,
        cwd=project_root,
        messages=(_user_message("msg-embedding-saturated", "How should I verify service changes?"),),
    )

    assert "Semantic Rust Checks" in fragments[0]
    assert len(trace["lexical_doc_ids"]) == 6
    assert len(trace["candidate_doc_ids"]) == len(trace["lexical_doc_ids"]) + len(trace["divergence"]["embedding_only"])
    assert rerank_provider.calls
    assert "Semantic Rust Checks" in rerank_provider.calls[0][1]


def test_long_term_retrieval_rerank_skips_when_deterministic_choice_is_clear(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    memory_root = project_root / ".claude" / "memory" / "documents" / "shared"
    _write_v2_memory_artifact(
        memory_root / "pytest-command.md",
        title="Pytest Command",
        content="Use pytest -q for concise Python test runs.",
        scope="project",
        memory_kind="workflow_command",
        tags=("pytest", "python"),
    )
    _write_v2_memory_artifact(
        memory_root / "npm-build.md",
        title="NPM Build",
        content="Run npm build for release packaging checks.",
        scope="project",
        memory_kind="workflow_command",
        tags=("frontend", "release"),
    )

    rerank_provider = FakeRerankProvider(("Pytest Command",))
    manager = MemoryManager(
        project_root=project_root,
        rerank_provider=rerank_provider,
    )
    agent = AgentDefinition(name="main-router", description="router", prompt="route")
    manager.initialize_session(session_id="session-rerank-skip", agent=agent, cwd=project_root)

    fragments, trace = manager.collect_with_trace(
        session_id="session-rerank-skip",
        turn_id="turn-rerank-skip",
        agent=agent,
        cwd=project_root,
        messages=(_user_message("msg-rerank-skip", "How should I run pytest -q here?"),),
    )

    assert any("Pytest Command" in fragment for fragment in fragments)
    assert trace["rerank"]["status"] == "skipped"
    assert trace["rerank"]["triggered"] is False
    assert rerank_provider.calls == []


def test_long_term_retrieval_uses_rerank_when_hybrid_shortlists_diverge(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    memory_root = project_root / ".claude" / "memory" / "documents" / "shared"
    _write_v2_memory_artifact(
        memory_root / "python-verification.md",
        title="Python Verification",
        content="Use pytest -q first when you need a quick Python confidence check.",
        scope="project",
        memory_kind="workflow_command",
        tags=("python", "verification"),
    )
    _write_v2_memory_artifact(
        memory_root / "verification-playbook.md",
        title="Verification Playbook",
        content="Start with the smallest targeted check before broad validation passes.",
        scope="project",
        memory_kind="project_convention",
        tags=("workflow", "verification"),
    )

    embedding_provider = FakeEmbeddingShortlistProvider({"Verification Playbook": 0.9})
    rerank_provider = FakeRerankProvider(("Verification Playbook", "Python Verification"))
    manager = MemoryManager(
        project_root=project_root,
        retrieval_policy=MemoryRetrievalPolicy(embedding_score_weight=0.0),
        embedding_shortlist_provider=embedding_provider,
        rerank_provider=rerank_provider,
    )
    agent = AgentDefinition(name="main-router", description="router", prompt="route")
    manager.initialize_session(session_id="session-rerank-success", agent=agent, cwd=project_root)

    fragments, trace = manager.collect_with_trace(
        session_id="session-rerank-success",
        turn_id="turn-rerank-success",
        agent=agent,
        cwd=project_root,
        messages=(_user_message("msg-rerank-success", "How should I verify Python changes?"),),
    )

    assert "Verification Playbook" in fragments[0]
    assert trace["rerank"]["status"] == "success"
    assert trace["rerank"]["triggered"] is True
    assert "lexical_embedding_divergence" in trace["rerank"]["reasons"]
    assert rerank_provider.calls


def test_long_term_retrieval_reports_budget_denied_when_rerank_would_trigger(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    memory_root = project_root / ".claude" / "memory" / "documents" / "shared"
    _write_v2_memory_artifact(
        memory_root / "python-verification.md",
        title="Python Verification",
        content="Use pytest -q first when you need a quick Python confidence check.",
        scope="project",
        memory_kind="workflow_command",
        tags=("python", "verification"),
    )
    _write_v2_memory_artifact(
        memory_root / "verification-playbook.md",
        title="Verification Playbook",
        content="Start with the smallest targeted check before broad validation passes.",
        scope="project",
        memory_kind="project_convention",
        tags=("workflow", "verification"),
    )

    embedding_provider = FakeEmbeddingShortlistProvider({"Verification Playbook": 0.9})
    rerank_provider = FakeRerankProvider(("Verification Playbook", "Python Verification"))
    manager = MemoryManager(
        project_root=project_root,
        retrieval_policy=MemoryRetrievalPolicy(
            embedding_score_weight=0.0,
            rerank_budget_available=False,
        ),
        embedding_shortlist_provider=embedding_provider,
        rerank_provider=rerank_provider,
    )
    agent = AgentDefinition(name="main-router", description="router", prompt="route")
    manager.initialize_session(session_id="session-rerank-budget", agent=agent, cwd=project_root)

    fragments, trace = manager.collect_with_trace(
        session_id="session-rerank-budget",
        turn_id="turn-rerank-budget",
        agent=agent,
        cwd=project_root,
        messages=(_user_message("msg-rerank-budget", "How should I verify Python changes?"),),
    )

    assert "Python Verification" in fragments[0]
    assert trace["rerank"]["status"] == "budget_denied"
    assert trace["rerank"]["triggered"] is False
    assert rerank_provider.calls == []


def test_long_term_retrieval_applies_contested_stale_and_confidence_controls(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    memory_root = project_root / ".claude" / "memory" / "documents" / "shared"
    _write_v2_memory_artifact(
        memory_root / "fresh-pytest.md",
        title="Fresh Pytest Workflow",
        content="Use pytest -q first for fast Python verification.",
        scope="project",
        memory_kind="workflow_command",
        tags=("pytest", "python"),
        extra_metadata={"confidence": 0.95},
    )
    _write_v2_memory_artifact(
        memory_root / "contested-pytest.md",
        title="Contested Pytest Workflow",
        content="Run the full test suite before every small Python change.",
        scope="project",
        memory_kind="workflow_command",
        tags=("pytest", "python"),
        extra_metadata={"contested": True, "confidence": 0.9},
    )
    _write_v2_memory_artifact(
        memory_root / "stale-pytest.md",
        title="Stale Pytest Workflow",
        content="Use pytest -q after opening the repo root.",
        scope="project",
        memory_kind="workflow_command",
        tags=("pytest", "python"),
        extra_metadata={"stale_after": "2026-04-01T04:00:00Z", "confidence": 0.85},
    )
    _write_v2_memory_artifact(
        memory_root / "low-confidence.md",
        title="Low Confidence Pytest Note",
        content="Maybe use a broad test sweep for Python changes.",
        scope="project",
        memory_kind="workflow_command",
        tags=("pytest", "python"),
        extra_metadata={"confidence": 0.2},
    )

    manager = MemoryManager(
        project_root=project_root,
        retrieval_limit=3,
        retrieval_policy=MemoryRetrievalPolicy(
            contested_policy="decay",
            contested_decay_penalty=4.0,
            stale_decay_penalty=2.0,
            minimum_confidence=0.5,
        ),
    )
    agent = AgentDefinition(name="main-router", description="router", prompt="route")
    manager.initialize_session(session_id="session-scoring-controls", agent=agent, cwd=project_root)

    fragments, trace = manager.collect_with_trace(
        session_id="session-scoring-controls",
        turn_id="turn-scoring-controls",
        agent=agent,
        cwd=project_root,
        messages=(_user_message("msg-scoring-controls", "How should I run pytest for Python changes?"),),
    )

    assert "Fresh Pytest Workflow" in fragments[0]
    assert not any("Low Confidence Pytest Note" in fragment for fragment in fragments)
    assert "confidence_below_threshold" in trace["applied_filters"]
    assert "contested_entry" in trace["decays"]
    assert "stale_beyond_threshold" in trace["decays"]


def test_embedding_shortlist_preserves_contested_decay_penalties(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    memory_root = project_root / ".claude" / "memory" / "documents" / "shared"
    _write_v2_memory_artifact(
        memory_root / "fresh-pytest.md",
        title="Fresh Pytest Workflow",
        content="Use pytest -q first for fast Python verification.",
        scope="project",
        memory_kind="workflow_command",
        tags=("pytest", "python"),
        extra_metadata={"confidence": 0.95},
    )
    _write_v2_memory_artifact(
        memory_root / "contested-pytest.md",
        title="Contested Pytest Workflow",
        content="Run the full test suite before every small Python change.",
        scope="project",
        memory_kind="workflow_command",
        tags=("pytest", "python"),
        extra_metadata={"contested": True, "confidence": 0.9},
    )

    embedding_provider = FakeEmbeddingShortlistProvider({"Contested Pytest Workflow": 1.0})
    manager = MemoryManager(
        project_root=project_root,
        retrieval_limit=1,
        retrieval_policy=MemoryRetrievalPolicy(
            contested_policy="decay",
            contested_decay_penalty=10.0,
        ),
        embedding_shortlist_provider=embedding_provider,
    )
    agent = AgentDefinition(name="main-router", description="router", prompt="route")
    manager.initialize_session(session_id="session-embedding-decay", agent=agent, cwd=project_root)

    fragments, trace = manager.collect_with_trace(
        session_id="session-embedding-decay",
        turn_id="turn-embedding-decay",
        agent=agent,
        cwd=project_root,
        messages=(_user_message("msg-embedding-decay", "How should I run pytest for Python changes?"),),
    )

    assert "Fresh Pytest Workflow" in fragments[0]
    assert "embedding_shortlist" in trace["applied_filters"]
    assert "contested_entry" in trace["decays"]
    assert embedding_provider.calls


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

    controller._messages = [
        replace(
            message,
            content="Compacted conversation summary:\nUnrelated compaction details only.",
            metadata={
                **message.metadata,
                "compaction": {
                    **message.metadata["compaction"],
                    "summary": {
                        **message.metadata["compaction"]["summary"],
                        "text": "Unrelated compaction details only.",
                    },
                },
            },
        )
        if message.metadata.get("compaction_summary")
        else message
        for message in controller._messages
    ]
    controller.state.metadata["compaction_summary"] = {
        "summary_id": "mutated",
        "text": "Unrelated compaction details only.",
        "source_message_ids": [],
        "message_count": 0,
        "metadata": {"mutated": True},
    }

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
    assert not any("Unrelated compaction details only." in fragment for fragment in fragments)


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

    asyncio.run(
        runtime.run_prompt(
            "Delegate this temporary refactor local memory turn",
            session_id="session-delegate",
            cwd=workspace,
        )
    )

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


def test_background_extraction_persists_synthesized_memory_after_turn_completion(tmp_path: Path) -> None:
    async def scenario() -> tuple[Path, MemoryTurnResult, object, SessionController]:
        project_root = tmp_path / "project"
        project_root.mkdir()
        model_client = FakeModelClient(
            [
                [
                    ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-bg-1"}),
                    ModelStreamEvent(
                        ModelStreamEventType.CONTENT_DELTA,
                        {
                            "text": "When verifying small Python changes, start with `pytest -q` before broader checks."
                        },
                    ),
                    ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
                ],
                [
                    ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-bg-2"}),
                    ModelStreamEvent(
                        ModelStreamEventType.CONTENT_DELTA,
                        {
                            "text": "For the agent, start with `pytest -q` before broader validation, and keep the pytest debugging thread focused."
                        },
                    ),
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
            session_id="session-background-memory",
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

        await controller.start()
        controller.enqueue_event(
            InboundEvent(
                InboundEventType.USER_PROMPT,
                "I prefer concise answers. We are debugging pytest failures in this repo.",
            )
        )
        await controller.run_until_idle()
        controller.enqueue_event(
            InboundEvent(
                InboundEventType.USER_PROMPT,
                "I prefer concise answers. Please keep pytest guidance short while we debug pytest failures.",
            )
        )
        await controller.run_until_idle()

        task_ids = controller.state.metadata.get("background_memory_tasks")
        assert isinstance(task_ids, list)
        task_id = str(task_ids[-1])
        result = await services.memory.wait_for_background_extraction(task_id)
        task = services.task_manager.get(task_id)
        return project_root, result, task, controller

    project_root, result, task, controller = asyncio.run(scenario())

    assert task is not None
    assert task.status == TaskStatus.COMPLETED
    assert len(result.persisted_documents) >= 2

    preferences = list((project_root / ".claude" / "memory" / "documents" / "preferences").glob("*.md"))
    topics = list((project_root / ".claude" / "memory" / "documents" / "topics").glob("*.md"))
    agent_notes = list(
        (project_root / ".claude" / "memory" / "agents" / "main-router" / "documents" / "durable-notes").glob("*.md")
    )
    assert preferences
    assert topics
    assert agent_notes
    assert any("background_extractor" in path.read_text(encoding="utf-8") for path in preferences)
    assert any("source_roles:" in path.read_text(encoding="utf-8") for path in preferences)
    assert "confidence:" in topics[0].read_text(encoding="utf-8")
    assert "Agent Note main-router" in agent_notes[0].read_text(encoding="utf-8")
    assert controller.state.metadata["background_memory_tasks"]


def test_background_extraction_queue_coalesces_and_merges_trailing_runs(tmp_path: Path) -> None:
    async def scenario():
        project_root = tmp_path / "project"
        project_root.mkdir()
        service = MemoryManagerService(project_root=project_root)
        agent = AgentDefinition(name="main-router", description="router", prompt="route")
        await service.start_session(
            session_id="session-background-queue",
            agent=agent,
            cwd=project_root,
        )
        task_manager = TaskManager()
        first_task_id = await service.schedule_background_extraction(
            session_id="session-background-queue",
            agent=agent,
            cwd=project_root,
            messages=(
                _user_message("msg-pref-1", "I prefer concise answers."),
                RuntimeMessage(
                    message_id="msg-agent-1",
                    role=MessageRole.ASSISTANT,
                    content="When verifying small Python changes, start with `pytest -q` before broader checks.",
                ),
            ),
            task_manager=task_manager,
        )
        second_task_id = await service.schedule_background_extraction(
            session_id="session-background-queue",
            agent=agent,
            cwd=project_root,
            messages=(
                _user_message("msg-pref-1", "I prefer concise answers."),
                _user_message("msg-pref-2", "I prefer concise answers."),
                RuntimeMessage(
                    message_id="msg-agent-1",
                    role=MessageRole.ASSISTANT,
                    content="When verifying small Python changes, start with `pytest -q` before broader checks.",
                ),
                RuntimeMessage(
                    message_id="msg-agent-2",
                    role=MessageRole.ASSISTANT,
                    content="For the agent, start with `pytest -q` before broader validation.",
                ),
            ),
            task_manager=task_manager,
        )
        result = await service.wait_for_background_extraction(str(first_task_id))
        task = task_manager.get(str(first_task_id))
        return project_root, first_task_id, second_task_id, result, task

    project_root, first_task_id, second_task_id, result, task = asyncio.run(scenario())

    assert first_task_id == second_task_id
    assert task is not None
    assert task.status == TaskStatus.COMPLETED
    assert task.metadata["queued_merge"] is True
    assert any(document.kind == "preference" for document in result.persisted_documents)
    assert any(document.kind == "agent_note" for document in result.persisted_documents)
    preferences = list((project_root / ".claude" / "memory" / "documents" / "preferences").glob("*.md"))
    agent_notes = list(
        (project_root / ".claude" / "memory" / "agents" / "main-router" / "documents" / "durable-notes").glob("*.md")
    )
    assert len(preferences) == 1
    assert len(agent_notes) == 1


def test_record_turn_with_receipts_merges_provenance_for_existing_project_convention(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    manager = MemoryManager(project_root=project_root)
    agent = AgentDefinition(name="main-router", description="router", prompt="route")
    manager.initialize_session(session_id="session-convention-merge", agent=agent, cwd=project_root)

    first = manager.record_turn_with_receipts(
        session_id="session-convention-merge",
        agent=agent,
        cwd=project_root,
        messages=(
            _user_message("msg-convention-1", "The project uses pytest."),
        ),
    )
    second = manager.record_turn_with_receipts(
        session_id="session-convention-merge",
        agent=agent,
        cwd=project_root,
        messages=(
            _user_message("msg-convention-2", "The project uses pytest."),
        ),
    )

    assert any(receipt.action == "persisted" for receipt in first.receipts)
    assert any(receipt.action == "merged" for receipt in second.receipts)
    conventions = sorted((project_root / ".claude" / "memory" / "documents" / "conventions").glob("*.md"))
    assert len(conventions) == 1
    convention_text = conventions[0].read_text(encoding="utf-8")
    assert "merge_policy: merge_with_provenance" in convention_text
    assert "msg-convention-1" in convention_text
    assert "msg-convention-2" in convention_text


def test_agent_namespace_overwrite_supersedes_existing_artifact_and_decay_prefers_latest(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    manager = MemoryManager(project_root=project_root)
    agent = AgentDefinition(name="main-router", description="router", prompt="route")
    manager.initialize_session(session_id="session-agent-overwrite", agent=agent, cwd=project_root)

    manager.record_turn_with_receipts(
        session_id="session-agent-overwrite",
        agent=agent,
        cwd=project_root,
        messages=(
            RuntimeMessage(
                message_id="msg-agent-1",
                role=MessageRole.ASSISTANT,
                content="When verifying small Python changes, start with `pytest -q` before broader checks.",
            ),
        ),
    )
    second = manager.record_turn_with_receipts(
        session_id="session-agent-overwrite",
        agent=agent,
        cwd=project_root,
        messages=(
            RuntimeMessage(
                message_id="msg-agent-2",
                role=MessageRole.ASSISTANT,
                content="When verifying small Python changes, start with `pytest -q` and inspect failing modules before broader checks.",
            ),
        ),
    )

    namespace_manifest = json.loads(
        (
            project_root
            / ".claude"
            / "memory"
            / "agents"
            / "main-router"
            / "namespace-manifest.json"
        ).read_text(encoding="utf-8")
    )
    assert sum(1 for entry in namespace_manifest["entries"] if entry.get("superseded") is True) == 1
    superseding_receipt = next(receipt for receipt in second.receipts if receipt.action == "persisted")
    assert superseding_receipt.reason == "superseded_existing"
    assert superseding_receipt.supersedes

    fragments, trace = manager.collect_with_trace(
        session_id="session-agent-overwrite",
        turn_id="turn-agent-overwrite",
        agent=agent,
        cwd=project_root,
        messages=(_user_message("msg-agent-query", "How should I run pytest for Python changes?"),),
    )

    assert any("inspect failing modules" in fragment for fragment in fragments)
    assert "superseded_artifact" in trace["decays"]
    assert trace["selected_doc_ids"][0] == str(superseding_receipt.path.relative_to(project_root / ".claude" / "memory"))


def test_background_extraction_is_merge_safe_for_conflict_keys(tmp_path: Path) -> None:
    async def scenario():
        project_root = tmp_path / "project"
        project_root.mkdir()
        service = MemoryManagerService(project_root=project_root)
        agent = AgentDefinition(name="main-router", description="router", prompt="route")
        await service.start_session(
            session_id="session-background-conflict",
            agent=agent,
            cwd=project_root,
        )
        first_task_id = await service.schedule_background_extraction(
            session_id="session-background-conflict",
            agent=agent,
            cwd=project_root,
            messages=(
                _user_message("msg-topic-1", "Pytest debugging is the main issue right now."),
                RuntimeMessage(
                    message_id="msg-topic-0",
                    role=MessageRole.USER,
                    content="Pytest debugging is the main ongoing issue.",
                ),
                RuntimeMessage(
                    message_id="msg-topic-2",
                    role=MessageRole.ASSISTANT,
                    content="Pytest debugging still needs a focused verification plan.",
                ),
                RuntimeMessage(
                    message_id="msg-topic-3",
                    role=MessageRole.TOOL,
                    content="Pytest debugging output shows a failing fixture.",
                ),
            ),
        )
        first_result = await service.wait_for_background_extraction(str(first_task_id))
        second_task_id = await service.schedule_background_extraction(
            session_id="session-background-conflict",
            agent=agent,
            cwd=project_root,
            messages=(
                _user_message("msg-topic-1", "Pytest debugging is the main issue right now."),
                RuntimeMessage(
                    message_id="msg-topic-0",
                    role=MessageRole.USER,
                    content="Pytest debugging is the main ongoing issue.",
                ),
                RuntimeMessage(
                    message_id="msg-topic-2",
                    role=MessageRole.ASSISTANT,
                    content="Pytest debugging now points at a different verification branch.",
                ),
                RuntimeMessage(
                    message_id="msg-topic-4",
                    role=MessageRole.TOOL,
                    content="Pytest debugging output now highlights another fixture chain.",
                ),
            ),
        )
        second_result = await service.wait_for_background_extraction(str(second_task_id))
        return project_root, first_result, second_result

    project_root, first_result, second_result = asyncio.run(scenario())

    assert any(document.kind == "topic_memory" for document in first_result.persisted_documents)
    assert any(receipt.action == "staged_contested" for receipt in second_result.receipts)
    topic_documents = list((project_root / ".claude" / "memory" / "documents" / "topics").glob("*.md"))
    assert len(topic_documents) == 2
    assert any("contested: true" in path.read_text(encoding="utf-8") for path in topic_documents)
    assert any("retention: review_required" in path.read_text(encoding="utf-8") for path in topic_documents)

    manager = MemoryManager(project_root=project_root)
    agent = AgentDefinition(name="main-router", description="router", prompt="route")
    manager.initialize_session(session_id="session-background-conflict", agent=agent, cwd=project_root)
    fragments, trace = manager.collect_with_trace(
        session_id="session-background-conflict",
        turn_id="turn-background-conflict",
        agent=agent,
        cwd=project_root,
        messages=(_user_message("msg-topic-query", "What should I remember about pytest debugging?"),),
    )
    assert not any("different verification branch" in fragment for fragment in fragments)
    assert "contested_policy:block" in trace["applied_filters"]


def test_session_controller_records_memory_diagnostics_for_retrieval_and_write_receipts(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    memory_root = project_root / ".claude" / "memory" / "documents" / "shared"
    _write_v2_memory_artifact(
        memory_root / "pytest-workflow.md",
        title="Pytest Workflow",
        content="Use pytest -q for concise unit test runs.",
        scope="project",
        memory_kind="workflow_command",
        extra_metadata={"conflict_key": "workflow_command.pytest-q"},
    )

    model_client = FakeModelClient(
        [
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-memory-diagnostics"}),
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
        session_id="session-memory-diagnostics",
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
            "How should I run pytest here? I prefer concise answers.",
        )
    )
    asyncio.run(controller.run_until_idle())

    diagnostics_history = controller.state.metadata.get("memory_diagnostics")
    assert isinstance(diagnostics_history, list) and diagnostics_history
    diagnostics = diagnostics_history[-1]
    assert diagnostics["retrieval"]["selected_doc_ids"]
    assert any(receipt["fact_type"] == "preference" for receipt in diagnostics["write_receipts"])
    assert any(receipt["source_pathway"] == "rule" for receipt in diagnostics["write_receipts"])

    notification = controller.runtime_services.host.current_notifications()[-1]
    assert notification.metadata["memory_diagnostics"]["retrieval"] == diagnostics["retrieval"]
    assert notification.metadata["memory_diagnostics"]["write_receipts"] == diagnostics["write_receipts"]
    request_diagnostics = model_client.requests[0].turn_context.metadata["memory_diagnostics"]
    assert request_diagnostics["retrieval"]["selected_doc_ids"] == diagnostics["retrieval"]["selected_doc_ids"]


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
    memory_kind: str = "note",
    namespace: str = "shared",
    agent_namespace: str | None = None,
    tags: tuple[str, ...] = ("testing",),
    extra_metadata: dict[str, object] | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    metadata: dict[str, object] = {
        "memory_kind": memory_kind,
        "scope": scope,
        "namespace": namespace,
        "agent_namespace": agent_namespace,
        "retention": "durable_until_superseded",
        "source_pathway": "rule",
        "created_at": "2026-04-17T04:00:00Z",
        "last_confirmed_at": "2026-04-17T04:00:00Z",
        "tags": list(tags),
    }
    if extra_metadata is not None:
        metadata.update(extra_metadata)
    path.write_text(
        serialize_memory_artifact(title, content, metadata),
        encoding="utf-8",
    )
