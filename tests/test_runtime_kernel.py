import asyncio
from dataclasses import replace
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError

from runtime.builtins import load_builtin_pack
from runtime.builtins.tools import builtin_tools
from runtime.context_window import ModelContextWindowProfile, RouteContextWindowPolicy
from runtime.contracts import MessageRole
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
)
from runtime.hosts.base import NullHostAdapter
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
from runtime.runtime_services import NoopMemoryService
from runtime.tool_runtime import ToolContext
from runtime.turn_engine import (
    ModelRequest,
    ModelStreamEvent,
    ModelStreamEventType,
    NormalizedModelCapabilities,
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
    assert "verify" in full_skill_names
    assert next(tool for tool in full_pack.tools if tool.name == "read").metadata["builtin_owner"] == "runtime-devtools"
    assert next(agent for agent in full_pack.agents if agent.name == "verification").metadata["builtin_owner"] == "runtime-devtools"


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
    assert "read" in full_tools
    assert "remember" in full_skills
    assert "verification" in full_agents
    assert "explore" in full_agents


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
    assert runtime.team_control_plane is not None
    assert runtime.team_message_bus is not None
    assert runtime.team_workflows is not None
    assert runtime.services.teammates is runtime.teammates
    assert runtime.services.team_control_plane is runtime.team_control_plane
    assert runtime.services.team_message_bus is runtime.team_message_bus
    assert runtime.services.team_workflows is runtime.team_workflows

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


def test_runtime_full_distribution_keeps_devtools_replacement_rules(tmp_path: Path) -> None:
    read_replacement = replace(
        next(tool for tool in builtin_tools() if tool.name == "read"),
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


def test_agent_definition_hooks_emit_warning_and_are_not_registered(tmp_path: Path) -> None:
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
    assert agent.metadata["hook_surface_status"] == "compatibility-only"
    assert any(diag.code == "agent_hooks_ignored" for diag in runtime.kernel.diagnostics)
    assert session.list_hooks(HookInventoryQuery(include_inactive=True)) == ()


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
