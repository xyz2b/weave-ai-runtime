import asyncio
from pathlib import Path

from claude_agent_runtime.contracts import MessageRole
from claude_agent_runtime.definitions import (
    AgentDefinition,
    DefinitionOrigin,
    DefinitionSource,
)
from claude_agent_runtime.hosts.base import NullHostAdapter
from claude_agent_runtime.runtime_kernel import (
    BuiltinPackConfig,
    DefinitionSourcePaths,
    HostBinding,
    RuntimeConfig,
    assemble_host_runtime,
    assemble_runtime,
    build_runtime_kernel,
)
from claude_agent_runtime.turn_engine import ModelRequest, ModelStreamEvent, ModelStreamEventType


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
