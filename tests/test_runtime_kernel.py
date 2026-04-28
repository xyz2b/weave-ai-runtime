import asyncio
import importlib
import os
import subprocess
import sys
from dataclasses import replace
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError

from runtime.builtins import load_builtin_pack
from runtime.builtins.tools import builtin_tools
from runtime.devtools.builtins import devtools_builtin_tools
from runtime.context_window import ModelContextWindowProfile, RouteContextWindowPolicy
from runtime.contracts import MessageRole, RuntimeMessage, TextBlock
from runtime.execution_policy import _narrow_tool_pool
from runtime.agent_execution import AgentRunRecord, AgentRunStatus, InMemoryChildRunStore, SpawnMode
from runtime.hooks import (
    HookActivationState,
    HookHandlerKind,
    HookHandlerManifest,
    HookInventoryQuery,
    HookRegistrationRequest,
    HookRegistrationScope,
    HookScopeLifetime,
    RuntimeHookPhase,
)
from runtime.openai_client import OPENAI_PROVIDER_NAME, OPENAI_ROUTE_NAME, _http_error_response
from runtime.definitions import (
    AgentDefinition,
    DefinitionOrigin,
    DefinitionSource,
    IsolationMode,
)
from runtime.hosts.base import NullHostAdapter
from runtime.jobs import FileJobStore, InMemoryJobStore
from runtime.runtime_kernel import (
    BuiltinPackConfig,
    DefinitionSourcePaths,
    HostBinding,
    ModelProviderBinding,
    ModelRouteBinding,
    RuntimeConfig,
    RuntimeDistribution,
    assemble_host_runtime,
    assemble_runtime,
    build_runtime_kernel,
)
from runtime.runtime_core_protocol_catalog import CORE_PROTOCOL_CATALOG_SCHEMA_VERSION
from runtime.runtime_package_protocols import RuntimeCapabilityKey
from runtime.runtime_services import NoopCompactionService, NoopMemoryService
from runtime.session_runtime import FileTranscriptStore, InMemoryTranscriptStore
from runtime.stores_file import FileChildRunStore
from runtime.task_lists import FileTaskListStore, InMemoryTaskListStore
from runtime.team_control_plane import InMemoryTeamStore
from runtime.team_message_bus import InMemoryTeamMessageStore
from runtime.team_workflows import InMemoryTeamWorkflowStore
from runtime.teammate_orchestration.mailbox import InMemoryTeammateMailbox
from runtime.tool_runtime import ToolContext
from runtime.turn_engine import (
    ModelRequest,
    ModelStreamEvent,
    ModelStreamEventType,
    NormalizedModelCapabilities,
    TranscriptEntry,
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


def _team_capability(runtime, key: RuntimeCapabilityKey):
    return runtime.resolve_capability(key.value)


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


def test_distribution_profiles_publish_expected_builtin_ownership(tmp_path: Path) -> None:
    core_config = RuntimeConfig(working_directory=tmp_path, distribution=RuntimeDistribution.CORE)
    default_config = RuntimeConfig(working_directory=tmp_path, distribution=RuntimeDistribution.DEFAULT)
    full_config = RuntimeConfig(working_directory=tmp_path, distribution=RuntimeDistribution.FULL)

    core_pack = load_builtin_pack(core_config.selected_first_party_packages())
    default_pack = load_builtin_pack(default_config.selected_first_party_packages())
    full_pack = load_builtin_pack(full_config.selected_first_party_packages())

    assert core_config.selected_first_party_packages() == ("runtime-core",)
    assert default_config.selected_first_party_packages() == (
        "runtime-core",
        "runtime-memory",
        "runtime-team",
    )
    assert full_config.selected_first_party_packages() == (
        "runtime-core",
        "runtime-memory",
        "runtime-team",
        "runtime-compaction",
        "runtime-isolation",
        "runtime-openai",
        "runtime-hosts-reference",
        "runtime-stores-file",
        "runtime-builtin-workflows",
        "runtime-planning",
        "runtime-devtools",
    )

    core_tool_names = {tool.name for tool in core_pack.tools}
    core_agent_names = {agent.name for agent in core_pack.agents}
    core_skill_names = {skill.name for skill in core_pack.skills}
    assert "read" not in core_tool_names
    assert "team_spawn" not in core_tool_names
    assert core_agent_names == {"general-purpose", "main-router"}
    assert core_skill_names == set()
    assert core_pack.agents[0].metadata["builtin_owner_role"] == "core"

    default_tool_names = {tool.name for tool in default_pack.tools}
    default_agent_names = {agent.name for agent in default_pack.agents}
    default_skill_names = {skill.name for skill in default_pack.skills}
    assert "team_spawn" in default_tool_names
    assert "read" not in default_tool_names
    assert default_agent_names == {"general-purpose", "main-router"}
    assert default_skill_names == {"remember"}
    assert next(tool for tool in default_pack.tools if tool.name == "team_spawn").metadata["builtin_owner"] == "runtime-team"
    assert next(skill for skill in default_pack.skills if skill.name == "remember").metadata["builtin_owner"] == "runtime-memory"

    full_tool_names = {tool.name for tool in full_pack.tools}
    full_agent_names = {agent.name for agent in full_pack.agents}
    full_skill_names = {skill.name for skill in full_pack.skills}
    assert "read" in full_tool_names
    assert "verification" in full_agent_names
    assert "planner" in full_agent_names
    assert "coordinator" in full_agent_names
    assert "worker" in full_agent_names
    assert "verify" in full_skill_names
    assert next(tool for tool in full_pack.tools if tool.name == "read").metadata["builtin_owner"] == "runtime-devtools"
    assert next(agent for agent in full_pack.agents if agent.name == "verification").metadata["builtin_owner"] == "runtime-devtools"
    planner = next(agent for agent in full_pack.agents if agent.name == "planner")
    coordinator = next(agent for agent in full_pack.agents if agent.name == "coordinator")
    worker = next(agent for agent in full_pack.agents if agent.name == "worker")
    plan = next(agent for agent in full_pack.agents if agent.name == "plan")
    assert planner.metadata["builtin_owner"] == "runtime-planning"
    assert coordinator.metadata["builtin_owner"] == "runtime-planning"
    assert worker.metadata["builtin_owner"] == "runtime-planning"
    assert planner.tools == ("task_*",)
    assert coordinator.tools == ("task_*", "job_*", "agent")
    assert worker.tools == ("agent", "ask_user", "skill", "sleep")
    assert worker.disallowed_tools == ()
    assert plan.metadata["builtin_owner"] == "runtime-devtools"


def test_runtime_planning_worker_profile_requires_explicit_optional_tool_composition(tmp_path: Path) -> None:
    full_pack = load_builtin_pack(
        RuntimeConfig(working_directory=tmp_path, distribution=RuntimeDistribution.FULL).selected_first_party_packages()
    )
    worker = next(agent for agent in full_pack.agents if agent.name == "worker")

    effective_tools = {
        tool.name
        for tool in _narrow_tool_pool(
            base_pool=full_pack.tools,
            allowed_tools=worker.tools or None,
            disallowed_tools=worker.disallowed_tools or None,
        )
    }

    assert effective_tools == {"agent", "ask_user", "skill", "sleep"}
    assert "bash" not in effective_tools
    assert "read" not in effective_tools
    assert "team_spawn" not in effective_tools
    assert "task_list" not in effective_tools
    assert "job_list" not in effective_tools


def test_core_builtin_catalog_excludes_optional_package_definitions() -> None:
    core_tool_names = {tool.name for tool in builtin_tools()}
    from runtime.builtins.agents import builtin_agents
    from runtime.builtins.skills import builtin_skills

    assert core_tool_names == {
        "agent",
        "skill",
        "task_create",
        "task_get",
        "task_update",
        "task_archive",
        "task_unarchive",
        "task_delete",
        "task_claim",
        "task_release",
        "task_assign_next",
        "task_block",
        "task_unblock",
        "task_list",
        "job_get",
        "job_list",
        "job_stop",
        "ask_user",
        "sleep",
    }
    assert {agent.name for agent in builtin_agents()} == {"general-purpose", "main-router"}
    assert builtin_skills() == ()


def test_runtime_core_build_does_not_import_optional_package_modules(
    tmp_path: Path,
    monkeypatch,
) -> None:
    first_party_loading = importlib.import_module("runtime.first_party_loading")
    original_import_module = first_party_loading.import_module
    blocked_modules = {
        "runtime.compaction.package",
        "runtime.devtools.builtins",
        "runtime.hosts.package",
        "runtime.isolation_package",
        "runtime.memory.builtins",
        "runtime.memory.package",
        "runtime.openai_package",
        "runtime.planning.builtins",
        "runtime.stores_file.package",
        "runtime.team.builtins",
        "runtime.team.assembly",
        "runtime.builtin_workflows.builtins",
    }

    def guarded_import_module(name: str, package: str | None = None):
        if name in blocked_modules:
            raise AssertionError(f"runtime-core should not import optional package module {name}")
        return original_import_module(name, package)

    monkeypatch.setattr(first_party_loading, "import_module", guarded_import_module)

    pack = load_builtin_pack(("runtime-core",))
    kernel = build_runtime_kernel(
        RuntimeConfig(
            working_directory=tmp_path,
            distribution=RuntimeDistribution.CORE,
        )
    )

    assert pack.packages == ("runtime-core",)
    assert kernel.first_party_packages == ("runtime-core",)


def test_distribution_profiles_expose_expected_visible_invocations(tmp_path: Path) -> None:
    core_root = tmp_path / "core"
    default_root = tmp_path / "default"
    full_root = tmp_path / "full"
    core_root.mkdir()
    default_root.mkdir()
    full_root.mkdir()

    core_model = FakeModelClient(
        [
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-core-visible"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "core"}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ]
        ]
    )
    default_model = FakeModelClient(
        [
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-default-visible"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "default"}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ]
        ]
    )
    full_model = FakeModelClient(
        [
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-full-visible"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "full"}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ]
        ]
    )

    core_runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=core_root,
            distribution=RuntimeDistribution.CORE,
            model_client=core_model,
        )
    )
    default_runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=default_root,
            distribution=RuntimeDistribution.DEFAULT,
            model_client=default_model,
        )
    )
    full_runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=full_root,
            distribution=RuntimeDistribution.FULL,
            model_client=full_model,
        )
    )

    asyncio.run(core_runtime.run_prompt("hello", session_id="core-visible"))
    asyncio.run(default_runtime.run_prompt("hello", session_id="default-visible"))
    asyncio.run(full_runtime.run_prompt("hello", session_id="full-visible"))

    core_tools = set(core_model.requests[0].turn_context.available_tools)
    core_skills = set(core_model.requests[0].turn_context.available_skills)
    default_tools = set(default_model.requests[0].turn_context.available_tools)
    default_skills = set(default_model.requests[0].turn_context.available_skills)
    default_agents = set(default_model.requests[0].turn_context.available_agents)
    full_tools = set(full_model.requests[0].turn_context.available_tools)
    full_skills = set(full_model.requests[0].turn_context.available_skills)
    full_agents = set(full_model.requests[0].turn_context.available_agents)

    assert "team_spawn" not in core_tools
    assert "remember" not in core_skills
    assert "read" not in core_tools
    assert "team_spawn" in default_tools
    assert "remember" in default_skills
    assert "read" not in default_tools
    assert "verification" not in default_agents
    assert "planner" not in default_agents
    assert "coordinator" not in default_agents
    assert "worker" not in default_agents
    assert "read" in full_tools
    assert "remember" in full_skills
    assert "verification" in full_agents
    assert "explore" in full_agents
    assert "planner" in full_agents
    assert "coordinator" in full_agents
    assert "worker" in full_agents


def test_runtime_core_distribution_remains_runnable_without_memory_or_devtools(tmp_path: Path) -> None:
    model_client = FakeModelClient(
        [
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-core"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "core reply"}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ]
        ]
    )
    replacement = AgentDefinition(
        name="main-router",
        description="core replacement router",
        prompt="route from core",
        origin=DefinitionOrigin(DefinitionSource.BUNDLED, path=Path("<core>")),
    )

    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            distribution=RuntimeDistribution.CORE,
            model_client=model_client,
            builtins=BuiltinPackConfig(agent_replacements={"main-router": replacement}),
        )
    )

    produced = asyncio.run(runtime.run_prompt("Hello core", session_id="session-core"))

    assert produced[-1].text == "core reply"
    assert runtime.kernel.distribution == RuntimeDistribution.CORE.value
    assert runtime.kernel.first_party_packages == ("runtime-core",)
    assert runtime.kernel.agent_registry.get("main-router").description == "core replacement router"
    assert runtime.kernel.tool_registry.get("read") is None
    assert runtime.kernel.tool_registry.get("team_spawn") is None
    assert runtime.kernel.skill_registry.get("remember") is None
    assert isinstance(runtime.services.memory, NoopMemoryService)
    assert OPENAI_PROVIDER_NAME not in runtime.kernel.config.model_providers
    assert OPENAI_ROUTE_NAME not in runtime.kernel.config.model_routes
    assert runtime.kernel.config.default_model_route is None


def test_runtime_default_distribution_wires_team_capability_out_of_the_box(tmp_path: Path) -> None:
    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            distribution=RuntimeDistribution.DEFAULT,
        )
    )

    team_create = runtime.kernel.tool_registry.get("team_create")
    assert team_create is not None
    assert runtime.kernel.first_party_packages == (
        "runtime-core",
        "runtime-memory",
        "runtime-team",
    )
    assert runtime.teammates is not None
    assert _team_capability(runtime, RuntimeCapabilityKey.TEAM_CONTROL_PLANE) is not None
    assert _team_capability(runtime, RuntimeCapabilityKey.TEAM_MESSAGE_BUS) is not None
    assert _team_capability(runtime, RuntimeCapabilityKey.TEAM_WORKFLOWS) is not None
    assert runtime.services.teammates is runtime.teammates
    assert runtime.services.resolve_team_control_plane() is _team_capability(
        runtime,
        RuntimeCapabilityKey.TEAM_CONTROL_PLANE,
    )
    assert runtime.services.resolve_team_message_bus() is _team_capability(
        runtime,
        RuntimeCapabilityKey.TEAM_MESSAGE_BUS,
    )
    assert runtime.services.resolve_team_workflows() is _team_capability(
        runtime,
        RuntimeCapabilityKey.TEAM_WORKFLOWS,
    )

    result = asyncio.run(
        team_create.execute(
            {},
            ToolContext(
                session_id="leader-session",
                turn_id="turn-1",
                agent_name="main-router",
                cwd=tmp_path,
                tool_registry=runtime.kernel.tool_registry,
                agent_registry=runtime.kernel.agent_registry,
                skill_registry=runtime.kernel.skill_registry,
                runtime_services=runtime.services,
            ),
        )
    )

    assert result["team_id"] != ""
    assert result["leader_session_id"] == "leader-session"
    assert result["created"] is True


def test_non_full_distributions_publish_devtools_and_planning_migration_diagnostics(tmp_path: Path) -> None:
    (tmp_path / "core-runtime").mkdir()
    (tmp_path / "default-runtime").mkdir()
    core_runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path / "core-runtime",
            distribution=RuntimeDistribution.CORE,
        )
    )
    default_runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path / "default-runtime",
            distribution=RuntimeDistribution.DEFAULT,
        )
    )

    for runtime in (core_runtime, default_runtime):
        devtools_diagnostic = next(
            diag for diag in runtime.kernel.diagnostics if diag.code == "runtime_devtools_not_selected"
        )
        planning_diagnostic = next(
            diag for diag in runtime.kernel.diagnostics if diag.code == "runtime_planning_not_selected"
        )
        assert devtools_diagnostic.details["target_distribution"] == RuntimeDistribution.FULL.value
        assert devtools_diagnostic.details["target_package"] == "runtime-devtools"
        assert "read" in devtools_diagnostic.details["tools"]
        assert "verification" in devtools_diagnostic.details["agents"]
        assert planning_diagnostic.details["target_distribution"] == RuntimeDistribution.FULL.value
        assert planning_diagnostic.details["target_package"] == "runtime-planning"
        assert "planner" in planning_diagnostic.details["agents"]
        assert planning_diagnostic.details["shared_primitives_owner"] == "runtime-core"
        assert runtime.services.metadata["migration"]["devtools"]["selected"] is False
        assert runtime.services.metadata["migration"]["planning_profiles"]["selected"] is False


def test_distribution_profiles_gate_runtime_mechanisms_and_store_defaults(tmp_path: Path) -> None:
    (tmp_path / "core-profile").mkdir()
    (tmp_path / "default-profile").mkdir()
    (tmp_path / "full-profile").mkdir()
    core_runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path / "core-profile",
            distribution=RuntimeDistribution.CORE,
        )
    )
    default_runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path / "default-profile",
            distribution=RuntimeDistribution.DEFAULT,
        )
    )
    full_runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path / "full-profile",
            distribution=RuntimeDistribution.FULL,
        )
    )

    assert isinstance(core_runtime.services.compaction, NoopCompactionService)
    assert isinstance(default_runtime.services.compaction, NoopCompactionService)
    assert not isinstance(full_runtime.services.compaction, NoopCompactionService)

    assert isinstance(core_runtime.services.transcript_store, InMemoryTranscriptStore)
    assert isinstance(default_runtime.services.transcript_store, InMemoryTranscriptStore)
    assert isinstance(full_runtime.services.transcript_store, FileTranscriptStore)
    assert isinstance(core_runtime.agent_runtime.run_store, InMemoryChildRunStore)
    assert isinstance(default_runtime.agent_runtime.run_store, InMemoryChildRunStore)
    assert isinstance(full_runtime.agent_runtime.run_store, FileChildRunStore)

    assert isinstance(core_runtime.services.job_service.store, InMemoryJobStore)
    assert isinstance(core_runtime.services.task_list_service.store, InMemoryTaskListStore)
    assert isinstance(default_runtime.services.job_service.store, InMemoryJobStore)
    assert isinstance(default_runtime.services.task_list_service.store, InMemoryTaskListStore)
    assert isinstance(full_runtime.services.job_service.store, FileJobStore)
    assert isinstance(full_runtime.services.task_list_service.store, FileTaskListStore)
    assert isinstance(_team_capability(default_runtime, RuntimeCapabilityKey.TEAM_CONTROL_PLANE).store, InMemoryTeamStore)
    assert isinstance(_team_capability(default_runtime, RuntimeCapabilityKey.TEAM_MESSAGE_BUS).store, InMemoryTeamMessageStore)
    assert isinstance(_team_capability(default_runtime, RuntimeCapabilityKey.TEAM_WORKFLOWS).store, InMemoryTeamWorkflowStore)
    assert isinstance(default_runtime.teammates.mailbox, InMemoryTeammateMailbox)
    assert core_runtime.query_closure_report()["persistence_profile"]["surfaces"]["child_runs"]["durability"] == (
        "non_durable"
    )
    assert full_runtime.query_closure_report()["persistence_profile"]["surfaces"]["child_runs"]["durability"] == (
        "durable"
    )

    assert full_runtime.services.metadata["migration"]["hook_contract"]["stable_handler_kinds"] == ["callback"]
    assert "runtime-hosts-reference" in full_runtime.services.metadata["first_party_package_catalog"]
    assert "runtime-planning" in full_runtime.services.metadata["first_party_package_catalog"]
    assert full_runtime.services.metadata["migration"]["planning_profiles"]["selected"] is True
    assert full_runtime.services.metadata["reference_hosts"] == ["cli", "sdk"]


def test_runtime_persistence_profiles_publish_all_surfaces_consistently(tmp_path: Path) -> None:
    expected_profiles = {
        RuntimeDistribution.CORE: {
            "profile_kind": "lightweight",
            "surfaces": {
                "transcript": {"durability": "non_durable", "provider": "InMemoryTranscriptStore"},
                "child_runs": {"durability": "non_durable", "provider": "InMemoryChildRunStore"},
                "jobs": {"durability": "non_durable", "provider": "InMemoryJobStore"},
                "task_lists": {"durability": "non_durable", "provider": "InMemoryTaskListStore"},
                "team_state": {"durability": "non_durable", "provider": None},
                "memory": {"durability": "non_durable", "provider": None},
            },
        },
        RuntimeDistribution.DEFAULT: {
            "profile_kind": "lightweight",
            "surfaces": {
                "transcript": {"durability": "non_durable", "provider": "InMemoryTranscriptStore"},
                "child_runs": {"durability": "non_durable", "provider": "InMemoryChildRunStore"},
                "jobs": {"durability": "non_durable", "provider": "InMemoryJobStore"},
                "task_lists": {"durability": "non_durable", "provider": "InMemoryTaskListStore"},
                "team_state": {"durability": "non_durable", "provider": "InMemoryTeamStore"},
                "memory": {"durability": "durable", "provider": "FileMemoryProvider"},
            },
        },
        RuntimeDistribution.FULL: {
            "profile_kind": "production_oriented",
            "surfaces": {
                "transcript": {"durability": "durable", "provider": "FileTranscriptStore"},
                "child_runs": {"durability": "durable", "provider": "FileChildRunStore"},
                "jobs": {"durability": "durable", "provider": "FileJobStore"},
                "task_lists": {"durability": "durable", "provider": "FileTaskListStore"},
                "team_state": {"durability": "durable", "provider": "FileBackedTeamStore"},
                "memory": {"durability": "durable", "provider": "FileMemoryProvider"},
            },
        },
    }

    for distribution, expected in expected_profiles.items():
        working_directory = tmp_path / distribution.value
        working_directory.mkdir()
        runtime = assemble_runtime(
            RuntimeConfig(
                working_directory=working_directory,
                distribution=distribution,
            )
        )

        profile = runtime.query_persistence_profile()

        assert runtime.services.query_persistence_profile() == profile
        assert profile["profile_name"] == distribution.value
        assert profile["profile_kind"] == expected["profile_kind"]
        assert profile["status"] == "pass"
        for surface_name, surface_expectation in expected["surfaces"].items():
            surface = profile["surfaces"][surface_name]
            assert surface["durability"] == surface_expectation["durability"]
            assert surface["provider"] == surface_expectation["provider"]


def test_runtime_full_durable_transcript_and_child_run_history_survive_reassembly(
    tmp_path: Path,
) -> None:
    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            distribution=RuntimeDistribution.FULL,
        )
    )

    asyncio.run(
        runtime.transcript_store.append(
            TranscriptEntry(
                session_id="session-durable",
                turn_id="turn-1",
                message=RuntimeMessage(
                    message_id="assistant-1",
                    role=MessageRole.ASSISTANT,
                    content=(TextBlock(text="persist me"),),
                ),
            )
        )
    )
    asyncio.run(
        runtime.agent_runtime.run_store.upsert(
            AgentRunRecord(
                run_id="run-1",
                parent_run_id=None,
                session_id="session-durable",
                parent_turn_id="turn-1",
                turn_id="child-turn-1",
                agent_name="delegate",
                spawn_mode=SpawnMode.BACKGROUND,
                status=AgentRunStatus.COMPLETED,
                terminal_metadata={"result": "persisted"},
            )
        )
    )

    reassembled = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            distribution=RuntimeDistribution.FULL,
        )
    )
    loaded_transcript = asyncio.run(reassembled.transcript_store.load("session-durable"))
    loaded_child_runs = asyncio.run(reassembled.agent_runtime.run_store.list_by_session("session-durable"))

    assert loaded_transcript.entries[0].message.text == "persist me"
    assert loaded_child_runs[0].run_id == "run-1"
    assert loaded_child_runs[0].status == AgentRunStatus.COMPLETED
    assert loaded_child_runs[0].terminal_metadata == {"result": "persisted"}
    assert reassembled.query_closure_report()["status"] == "closure-green"


def test_runtime_full_worktree_isolation_prepares_real_local_lease_and_cleans_up(
    tmp_path: Path,
) -> None:
    (tmp_path / "workspace").mkdir()
    (tmp_path / "workspace" / "keep.txt").write_text("keep", encoding="utf-8")
    (tmp_path / "workspace" / "nested").mkdir()
    (tmp_path / "workspace" / "nested" / "note.txt").write_text("nested", encoding="utf-8")
    (tmp_path / "workspace" / ".git").mkdir()
    (tmp_path / "workspace" / ".git" / "ignored.txt").write_text("git", encoding="utf-8")

    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path / "workspace",
            distribution=RuntimeDistribution.FULL,
        )
    )
    readiness = runtime.query_isolation_readiness()
    manager = runtime.services.resolve_isolation_service()
    lease = asyncio.run(
        manager.prepare(
            mode=IsolationMode.WORKTREE,
            session_id="session-worktree",
            agent_name="delegate",
            cwd=tmp_path / "workspace",
            metadata={"run_id": "run-worktree"},
        )
    )

    assert readiness["modes"]["worktree"] == {
        "status": "ready",
        "effective_mode": "worktree",
        "adapter": "WorktreeIsolationAdapter",
        "lease_kind": "filesystem_local_copy",
        "cleanup_owner": "runtime",
        "cleanup_lifecycle": "child_run_exit",
    }
    assert lease.working_directory != tmp_path / "workspace"
    assert lease.working_directory.exists()
    assert (lease.working_directory / "keep.txt").read_text(encoding="utf-8") == "keep"
    assert (lease.working_directory / "nested" / "note.txt").read_text(encoding="utf-8") == "nested"
    assert not (lease.working_directory / ".git").exists()
    assert lease.metadata["source_working_directory"] == str(tmp_path / "workspace")
    assert lease.metadata["lease_kind"] == "filesystem_local_copy"
    assert lease.metadata["cleanup_owner"] == "runtime"
    assert lease.metadata["cleanup_lifecycle"] == "child_run_exit"
    assert lease.lifecycle == ["prepared", "materialized"]

    asyncio.run(manager.cleanup(lease))

    assert lease.lifecycle[-2:] == ["cleaned", "released"]
    assert not lease.working_directory.exists()


def test_supported_distributions_publish_same_stable_core_protocol_catalog(tmp_path: Path) -> None:
    (tmp_path / "core-catalog").mkdir()
    (tmp_path / "default-catalog").mkdir()
    (tmp_path / "full-catalog").mkdir()

    core_runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path / "core-catalog",
            distribution=RuntimeDistribution.CORE,
        )
    )
    default_runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path / "default-catalog",
            distribution=RuntimeDistribution.DEFAULT,
        )
    )
    full_runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path / "full-catalog",
            distribution=RuntimeDistribution.FULL,
        )
    )

    core_catalog = core_runtime.metadata["core_protocol_catalog"]

    assert core_catalog["schema_version"] == CORE_PROTOCOL_CATALOG_SCHEMA_VERSION
    assert default_runtime.metadata["core_protocol_catalog"] == core_catalog
    assert full_runtime.metadata["core_protocol_catalog"] == core_catalog


def test_runtime_full_distribution_keeps_devtools_replacement_rules(tmp_path: Path) -> None:
    read_replacement = replace(
        next(tool for tool in devtools_builtin_tools() if tool.name == "read"),
        description="custom devtools read",
    )
    verification_replacement = AgentDefinition(
        name="verification",
        description="custom verification agent",
        prompt="verify replacements",
        origin=DefinitionOrigin(DefinitionSource.BUNDLED, path=Path("<verification>")),
    )

    kernel = build_runtime_kernel(
        RuntimeConfig(
            working_directory=tmp_path,
            distribution=RuntimeDistribution.FULL,
            builtins=BuiltinPackConfig(
                tool_replacements={"read": read_replacement},
                agent_replacements={"verification": verification_replacement},
            ),
        )
    )

    assert kernel.tool_registry.get("read") is not None
    assert kernel.tool_registry.get("read").description == "custom devtools read"
    assert kernel.agent_registry.get("verification") is not None
    assert kernel.agent_registry.get("verification").description == "custom verification agent"


def test_runtime_planning_package_can_be_explicitly_enabled_and_disabled(tmp_path: Path) -> None:
    core_with_planning = RuntimeConfig(
        working_directory=tmp_path / "core-with-planning",
        distribution=RuntimeDistribution.CORE,
        enabled_packages={"runtime-planning"},
    )
    full_without_planning = RuntimeConfig(
        working_directory=tmp_path / "full-without-planning",
        distribution=RuntimeDistribution.FULL,
        disabled_packages={"runtime-planning"},
    )

    core_with_planning_pack = load_builtin_pack(core_with_planning.selected_first_party_packages())
    full_without_planning_pack = load_builtin_pack(full_without_planning.selected_first_party_packages())

    assert core_with_planning.selected_first_party_packages() == ("runtime-core", "runtime-planning")
    assert "planner" in {agent.name for agent in core_with_planning_pack.agents}
    assert "coordinator" in {agent.name for agent in core_with_planning_pack.agents}
    assert "worker" in {agent.name for agent in core_with_planning_pack.agents}
    assert full_without_planning.selected_first_party_packages() == (
        "runtime-core",
        "runtime-memory",
        "runtime-team",
        "runtime-compaction",
        "runtime-isolation",
        "runtime-openai",
        "runtime-hosts-reference",
        "runtime-stores-file",
        "runtime-builtin-workflows",
        "runtime-devtools",
    )
    assert "planner" not in {agent.name for agent in full_without_planning_pack.agents}
    assert "coordinator" not in {agent.name for agent in full_without_planning_pack.agents}
    assert "worker" not in {agent.name for agent in full_without_planning_pack.agents}


def test_runtime_core_preserves_task_and_job_primitives_without_planning_package() -> None:
    core_pack = load_builtin_pack(("runtime-core",))

    core_tool_names = {tool.name for tool in core_pack.tools}
    core_agent_names = {agent.name for agent in core_pack.agents}

    assert "task_create" in core_tool_names
    assert "task_list" in core_tool_names
    assert "job_get" in core_tool_names
    assert "job_list" in core_tool_names
    assert "job_stop" in core_tool_names
    assert "planner" not in core_agent_names
    assert "coordinator" not in core_agent_names
    assert "worker" not in core_agent_names


def test_runtime_core_import_surface_does_not_eagerly_load_reference_hosts(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(repo_root / "src")
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import runtime.runtime_kernel; print('runtime.hosts.reference' in sys.modules)",
        ],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout.strip() == "False"


def test_runtime_builtin_workflow_pack_remains_runnable_without_devtools_package(tmp_path: Path) -> None:
    model_client = FakeModelClient(
        [
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-verify-core"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "verified"}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ]
        ]
    )
    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            distribution=RuntimeDistribution.CORE,
            enabled_packages={"runtime-builtin-workflows"},
            model_client=model_client,
        )
    )

    result = asyncio.run(
        runtime.skill_executor.execute(
            "verify",
            arguments=(),
            session_id="session-verify-core",
            cwd=tmp_path,
        )
    )

    assert runtime.kernel.agent_registry.get("verification") is None
    assert result.agent_result is not None
    assert result.agent_result.agent_name == "general-purpose"
    assert result.agent_result.status == "completed"


def test_agent_definition_hooks_are_rejected_by_default_and_are_not_registered(tmp_path: Path) -> None:
    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            builtins=BuiltinPackConfig(
                extra_agents=[
                    AgentDefinition(
                        name="hook-agent",
                        description="agent with ignored hooks",
                        prompt="Use compatibility surfaces.",
                        hooks={
                            RuntimeHookPhase.SESSION_START.value: {
                                "handler": lambda _payload: None,
                            }
                        },
                        origin=DefinitionOrigin(DefinitionSource.BUNDLED, path=Path("<hook-agent>")),
                    )
                ]
            ),
        )
    )

    agent = runtime.kernel.agent_registry.get("hook-agent")
    session = runtime.create_session(session_id="hook-agent-session", agent_name="hook-agent")

    assert agent is not None
    assert agent.hooks == {}
    assert agent.metadata["ignored_agent_hooks"] == (RuntimeHookPhase.SESSION_START.value,)
    assert agent.metadata["hook_surface_status"] == "rejected-by-default"
    assert any(diag.code == "agent_hooks_rejected" for diag in runtime.kernel.diagnostics)
    assert session.list_hooks(HookInventoryQuery(include_inactive=True)) == ()


def test_agent_definition_hooks_can_be_legacy_gated_explicitly(tmp_path: Path) -> None:
    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            legacy_compatibility={"families": ["agent_owned_hooks"]},
            builtins=BuiltinPackConfig(
                extra_agents=[
                    AgentDefinition(
                        name="hook-agent",
                        description="agent with gated hooks",
                        prompt="Use compatibility surfaces.",
                        hooks={
                            RuntimeHookPhase.SESSION_START.value: {
                                "handler": lambda _payload: None,
                            }
                        },
                        origin=DefinitionOrigin(DefinitionSource.BUNDLED, path=Path("<hook-agent>")),
                    )
                ]
            ),
        )
    )

    agent = runtime.kernel.agent_registry.get("hook-agent")

    assert agent is not None
    assert agent.hooks == {}
    assert agent.metadata["hook_surface_status"] == "legacy-mode-enabled"
    assert "agent_owned_hooks" in runtime.query_compatibility_retirement()["active_families"]
    assert runtime.query_closure_report()["status"] == "closure-red"


def test_runtime_core_distribution_supports_stable_hooks_and_compatibility_diagnostics(
    tmp_path: Path,
) -> None:
    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            distribution=RuntimeDistribution.CORE,
        )
    )

    handle = runtime.register_hook(
        HookRegistrationRequest(
            phase=RuntimeHookPhase.PRE_TOOL_USE.value,
            scope=HookRegistrationScope(
                lifetime=HookScopeLifetime.SESSION_TEMPLATE,
                session_id="session-core",
            ),
            handler=HookHandlerManifest(
                kind=HookHandlerKind.CALLBACK,
                callback=lambda _payload: None,
            ),
        )
    )
    runtime.services.hook_bus.materialize_session("session-core")
    inventory = runtime.list_hooks(
        HookInventoryQuery(
            session_id="session-core",
            phase=RuntimeHookPhase.PRE_TOOL_USE.value,
            activation_state=HookActivationState.ACTIVE,
        )
    )

    assert handle.activation_state == HookActivationState.PENDING_ACTIVATION
    assert inventory[0].phase == RuntimeHookPhase.PRE_TOOL_USE.value
    assert runtime.services.metadata["compatibility_surfaces"] == {
        "TaskManager": "compatibility-only",
        "runtime_context": "compatibility-only",
        "RuntimeServices.memory": "compatibility-only",
        "RuntimeServices.memory.collect": "compatibility-only",
        "RuntimeServices.compaction": "compatibility-only",
        "RuntimeServices.isolation": "compatibility-only",
        "RuntimeServices.hooks.collect": "compatibility-only",
        "RuntimeServices.task_discipline.collect": "compatibility-only",
        "RuntimeServices.compaction.prepare_turn": "compatibility-only",
        "RuntimeServices.compaction.collect": "compatibility-only",
        "RuntimeServices.teammates": "compatibility-only",
        "RuntimeAssembly.teammates": "compatibility-only",
    }


def test_runtime_task_manager_compatibility_wrapper_is_created_lazily(tmp_path: Path) -> None:
    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            distribution=RuntimeDistribution.CORE,
        )
    )

    assert runtime.services.tasks.manager is None
    assert runtime._task_manager is None
    assert runtime.services.metadata.get("compatibility_accesses") is None

    compat_task_manager = runtime.task_manager

    assert compat_task_manager is runtime.services.task_manager
    assert runtime.services.tasks.manager is compat_task_manager
    assert runtime._task_manager is compat_task_manager
    assert compat_task_manager.job_service is runtime.services.job_service
    assert runtime.services.metadata["compatibility_accesses"] == ["TaskManager"]
    assert runtime.services.metadata["package_lookup"]["canonical_control_plane_services"] == {
        "job_service": "RuntimeServices.job_service",
        "task_list_service": "RuntimeServices.task_list_service",
    }


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


def test_runtime_root_session_resolves_default_model_route_and_context_window(tmp_path: Path) -> None:
    model_client = FakeModelClient(
        [
            [
                ModelStreamEvent(
                    ModelStreamEventType.MESSAGE_START,
                    {"request_id": "req-route"},
                ),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "routed reply"}),
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
            model_providers={
                "provider-a": ModelProviderBinding(
                    client=model_client,
                    provider_name="provider-a",
                    capabilities=NormalizedModelCapabilities(),
                    context_window_profiles=(
                        ModelContextWindowProfile(
                            provider_name="provider-a",
                            model_selector="model-a",
                            max_input_tokens=64,
                            reserved_output_tokens=8,
                        ),
                    ),
                )
            },
            model_routes={
                "route-a": ModelRouteBinding(
                    provider_binding="provider-a",
                    provider_name="provider-a",
                    default_model="model-a",
                    context_window_policy=RouteContextWindowPolicy(
                        trigger_buffer_tokens=4,
                        policy_tag="route-a-policy",
                    ),
                )
            },
            default_model_route="route-a",
        )
    )

    produced = asyncio.run(runtime.run_prompt("Hello route", session_id="session-route"))

    assert produced[-1].text == "routed reply"
    assert len(model_client.requests) == 1
    request = model_client.requests[0]
    assert request.model == "model-a"
    assert request.requested_model_route is None
    assert request.resolved_model_route == "route-a"
    assert request.provider_name == "provider-a"
    assert request.context_window is not None
    assert request.context_window.max_input_tokens == 64
    assert request.context_window.policy_tag == "route-a-policy"
    assert request.metadata["context_window_policy_tag"] == "route-a-policy"
    assert request.metadata["resolved_model_route"] == "route-a"


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


def test_runtime_bundles_openai_route_and_surfaces_missing_credentials_at_invocation(
    tmp_path: Path,
) -> None:
    runtime = assemble_runtime(RuntimeConfig(working_directory=tmp_path))

    assert OPENAI_PROVIDER_NAME in runtime.kernel.config.model_providers
    assert OPENAI_ROUTE_NAME in runtime.kernel.config.model_routes
    assert runtime.kernel.config.default_model_route == OPENAI_ROUTE_NAME

    async def scenario():
        return [event async for event in runtime.stream_prompt("Hello runtime", session_id="openai-default")]

    events = asyncio.run(scenario())
    terminal = next(event for event in events if event.event_type.value == "terminal")

    assert terminal.terminal is not None
    assert terminal.terminal.metadata["failure_class"] == "auth_error"
    assert "OPENAI_API_KEY" in terminal.terminal.metadata["error"]


def test_runtime_bundled_openai_route_honors_openai_model_override(
    tmp_path: Path,
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_post_json(url: str, payload: dict[str, object], *, api_key: str) -> dict[str, object]:
        captured["url"] = url
        captured["payload"] = dict(payload)
        captured["api_key"] = api_key
        return {
            "id": "req-openai-env",
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "usage": {},
        }

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-env-override")
    monkeypatch.setattr("runtime.openai_client._post_json", fake_post_json)

    runtime = assemble_runtime(RuntimeConfig(working_directory=tmp_path))
    produced = asyncio.run(runtime.run_prompt("Hello runtime", session_id="openai-env"))

    assert produced[-1].text == "ok"
    assert captured["api_key"] == "test-key"
    assert captured["payload"]["model"] == "gpt-env-override"


def test_openai_http_error_response_preserves_retryable_context_and_output_limits() -> None:
    context_limit = _http_error_response(
        HTTPError(
            url="https://example.test",
            code=400,
            msg="Bad Request",
            hdrs=None,
            fp=BytesIO(
                b'{"error":{"message":"maximum context length exceeded","code":"context_length_exceeded"}}'
            ),
        )
    )
    output_limit = _http_error_response(
        HTTPError(
            url="https://example.test",
            code=400,
            msg="Bad Request",
            hdrs=None,
            fp=BytesIO(
                b'{"error":{"message":"maximum output tokens exceeded","code":"output_limit"}}'
            ),
        )
    )

    assert context_limit.terminal is not None
    assert context_limit.terminal.metadata["failure_class"] == "context_limit"
    assert context_limit.terminal.metadata["retryable"] is True
    assert output_limit.terminal is not None
    assert output_limit.terminal.metadata["failure_class"] == "output_limit"
    assert output_limit.terminal.metadata["retryable"] is True
