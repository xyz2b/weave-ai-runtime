import asyncio
from pathlib import Path

from claude_agent_runtime.contracts import (
    MessageAttachment,
    MessageRole,
    PromptContextEnvelope,
    RuntimeMessage,
    RuntimePrivateContext,
    ToolResultBlock,
)
from claude_agent_runtime.definitions import (
    AgentDefinition,
    DefinitionOrigin,
    DefinitionSource,
    InvocationDefinition,
    InvocationExecutionPolicy,
    InvocationHiddenReason,
    InvocationPathMatchState,
    InvocationResolutionContext,
    InvocationSourceKind,
    InvocationTargetKind,
    SkillDefinition,
    SkillExecutionContext,
)
from claude_agent_runtime.execution_policy import ExecutionPolicy, ExecutionPolicyState
from claude_agent_runtime.invocation_catalog import (
    McpPromptInvocationProvider,
    PluginCommandInvocationProvider,
    SkillInvocationProvider,
    SlashCommandInvocationProvider,
)
from claude_agent_runtime.permissions import PermissionContext
from claude_agent_runtime.registries import InvocationRegistry, SkillRegistry, ToolRegistry
from claude_agent_runtime.runtime_kernel import BuiltinPackConfig, RuntimeConfig, assemble_runtime
from claude_agent_runtime.session_runtime import InboundEvent, InboundEventType
from claude_agent_runtime.turn_engine import ModelRequest, ModelStreamEvent, ModelStreamEventType, TurnEngine


class FakeModelClient:
    def __init__(self, event_batches: list[list[ModelStreamEvent]]) -> None:
        self._event_batches = [list(batch) for batch in event_batches]
        self.requests: list[ModelRequest] = []

    async def complete(self, request: ModelRequest):  # pragma: no cover - protocol completeness
        raise NotImplementedError

    async def stream(self, request: ModelRequest):
        self.requests.append(request)
        batch = self._event_batches.pop(0) if self._event_batches else []
        for event in batch:
            yield event


def _origin(name: str, source: DefinitionSource = DefinitionSource.USER) -> DefinitionOrigin:
    return DefinitionOrigin(source=source, path=Path(f"/tmp/{name}/SKILL.md"))


def _message(
    *,
    text: str,
    metadata: dict[str, object] | None = None,
    attachments: tuple[object, ...] = (),
) -> RuntimeMessage:
    return RuntimeMessage(
        message_id="message",
        role=MessageRole.USER,
        content=text,
        metadata=metadata or {},
        attachments=attachments,
    )


def test_skill_invocation_provider_projects_visibility_and_execution_metadata() -> None:
    registry = SkillRegistry()
    registry.register(
        SkillDefinition(
            name="review",
            display_name="Code Review",
            description="Review the current changes",
            content="Review content",
            when_to_use="Use when code changes need inspection",
            user_invocable=False,
            disable_model_invocation=True,
            argument_hint="<path>",
            argument_names=("path",),
            execution_context=SkillExecutionContext.FORK,
            agent="reviewer",
            model="gpt-review",
            effort="high",
            allowed_tools=("read", "grep"),
            hooks={"post": "notify"},
            paths=("src/**/*.py",),
            origin=_origin("review"),
        )
    )

    invocation = SkillInvocationProvider(registry).list_invocations()[0]

    assert invocation.source_kind == InvocationSourceKind.SKILL_DIR
    assert invocation.display_name == "Code Review"
    assert invocation.argument_hint == "<path>"
    assert invocation.visibility_policy.user_invocable is False
    assert invocation.visibility_policy.model_invocable is False
    assert invocation.visibility_policy.paths == ("src/**/*.py",)
    assert invocation.visibility_policy.surface_hints["when_to_use"] == (
        "Use when code changes need inspection"
    )
    assert invocation.execution_policy is not None
    assert invocation.execution_policy.target_kind == InvocationTargetKind.SKILL
    assert invocation.execution_policy.target_name == "review"
    assert invocation.execution_policy.context == SkillExecutionContext.FORK.value
    assert invocation.execution_policy.allowed_tools == ("read", "grep")
    assert invocation.execution_policy.agent == "reviewer"
    assert invocation.execution_policy.model == "gpt-review"
    assert invocation.execution_policy.effort == "high"


def test_turn_engine_resolves_path_match_states_and_model_visibility(tmp_path: Path) -> None:
    registry = SkillRegistry()
    registry.register(
        SkillDefinition(
            name="always-on",
            description="Always available",
            content="always",
            origin=_origin("always-on"),
        )
    )
    registry.register(
        SkillDefinition(
            name="python-only",
            description="Python only",
            content="python",
            paths=("src/**/*.py",),
            origin=_origin("python-only"),
        )
    )
    registry.register(
        SkillDefinition(
            name="host-only",
            description="Host only",
            content="host",
            disable_model_invocation=True,
            origin=_origin("host-only"),
        )
    )
    engine = TurnEngine(
        model_client=FakeModelClient([]),
        tool_registry=ToolRegistry(),
        skill_registry=registry,
    )

    matched = engine.resolve_invocation_catalog(
        session_id="session",
        turn_id="turn",
        cwd=tmp_path,
        messages=(_message(text="Inspect src/app/main.py"),),
    )
    mismatch = engine.resolve_invocation_catalog(
        session_id="session",
        turn_id="turn",
        cwd=tmp_path,
        messages=(_message(text="Inspect README.md"),),
    )
    indeterminate = engine.resolve_invocation_catalog(
        session_id="session",
        turn_id="turn",
        cwd=tmp_path,
        messages=(),
    )

    assert {entry.capability.name for entry in matched.visible} == {
        "always-on",
        "python-only",
        "host-only",
    }
    assert {capability.name for capability in matched.visible_capabilities(model_invocable=True)} == {
        "always-on",
        "python-only",
    }
    assert matched.diagnostics_for("python-only").path_match_state == InvocationPathMatchState.MATCHED
    assert matched.diagnostics_for("host-only").model_invocable is False
    assert mismatch.diagnostics_for("python-only").hidden_reason == InvocationHiddenReason.PATH_MISMATCH
    assert (
        indeterminate.diagnostics_for("python-only").hidden_reason
        == InvocationHiddenReason.PATH_INDETERMINATE
    )


def test_tool_replay_keeps_latest_prompt_path_context(tmp_path: Path) -> None:
    registry = SkillRegistry()
    registry.register(
        SkillDefinition(
            name="python-only",
            description="Python only",
            content="python",
            paths=("src/**/*.py",),
            origin=_origin("python-only"),
        )
    )
    engine = TurnEngine(
        model_client=FakeModelClient([]),
        tool_registry=ToolRegistry(),
        skill_registry=registry,
    )

    catalog = engine.resolve_invocation_catalog(
        session_id="session",
        turn_id="turn",
        cwd=tmp_path,
        messages=(
            _message(text="Inspect src/app/main.py"),
            RuntimeMessage(
                message_id="assistant",
                role=MessageRole.ASSISTANT,
                content="calling read",
            ),
            RuntimeMessage(
                message_id="tool-result",
                role=MessageRole.USER,
                content=(ToolResultBlock(tool_use_id="call-1", content="{}"),),
                metadata={"tool_results": [{"tool_name": "read"}]},
            ),
        ),
    )

    assert {entry.capability.name for entry in catalog.visible} == {"python-only"}
    assert catalog.diagnostics_for("python-only").path_match_state == InvocationPathMatchState.MATCHED


def test_execution_policy_narrows_visible_invocations_and_diagnostics(tmp_path: Path) -> None:
    registry = SkillRegistry()
    registry.register(
        SkillDefinition(
            name="alpha",
            description="Alpha",
            content="alpha",
            origin=_origin("alpha"),
        )
    )
    registry.register(
        SkillDefinition(
            name="beta",
            description="Beta",
            content="beta",
            origin=_origin("beta"),
        )
    )
    engine = TurnEngine(
        model_client=FakeModelClient([]),
        tool_registry=ToolRegistry(),
        skill_registry=registry,
    )
    policy = ExecutionPolicyState(
        ExecutionPolicy(
            tool_pool=(),
            skill_pool=(registry.get("alpha"),),
            permission_context=PermissionContext(session_id="session"),
        )
    )

    catalog = engine.resolve_invocation_catalog(
        session_id="session",
        turn_id="turn",
        cwd=tmp_path,
        messages=(_message(text="Review the workspace"),),
        private_context=RuntimePrivateContext(policy_state=policy),
    )
    diagnostics = catalog.diagnostics_for("beta")

    assert {entry.capability.name for entry in catalog.visible} == {"alpha"}
    assert diagnostics.hidden_reason == InvocationHiddenReason.POLICY_NARROWED
    assert diagnostics.narrowed_by_policy["skill_pool"] == ("alpha",)
    assert diagnostics.narrowed_by_policy["blocked_by"] == "execution_policy.skill_pool"


def test_prompt_context_attachments_feed_invocation_path_matching(tmp_path: Path) -> None:
    docs_path = tmp_path / "docs" / "guide.md"
    docs_path.parent.mkdir(parents=True)
    docs_path.write_text("guide", encoding="utf-8")
    registry = SkillRegistry()
    registry.register(
        SkillDefinition(
            name="docs-helper",
            description="Docs helper",
            content="docs",
            paths=("docs/*.md",),
            origin=_origin("docs-helper"),
        )
    )
    engine = TurnEngine(
        model_client=FakeModelClient([]),
        tool_registry=ToolRegistry(),
        skill_registry=registry,
    )

    catalog = engine.resolve_invocation_catalog(
        session_id="session",
        turn_id="turn",
        cwd=tmp_path,
        messages=(),
        prompt_context=PromptContextEnvelope(
            attachments=(MessageAttachment(name="guide.md", path=str(docs_path)),)
        ),
    )

    assert {entry.capability.name for entry in catalog.visible} == {"docs-helper"}


def test_runtime_main_thread_uses_resolved_visible_invocations(tmp_path: Path) -> None:
    model_client = FakeModelClient(
        [
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-1"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "done"}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ]
        ]
    )
    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            model_client=model_client,
            builtins=BuiltinPackConfig(
                agents_enabled=False,
                skills_enabled=False,
                extra_agents=[
                    AgentDefinition(
                        name="main-router",
                        description="router",
                        prompt="route",
                    )
                ],
                extra_skills=[
                    SkillDefinition(
                        name="always-on",
                        description="Always available",
                        content="always",
                        origin=_origin("always-on"),
                    ),
                    SkillDefinition(
                        name="python-only",
                        description="Python only",
                        content="python",
                        paths=("src/**/*.py",),
                        origin=_origin("python-only"),
                    ),
                    SkillDefinition(
                        name="host-only",
                        description="Visible to host only",
                        content="host",
                        disable_model_invocation=True,
                        origin=_origin("host-only"),
                    ),
                ],
            ),
        )
    )

    asyncio.run(runtime.run_prompt("Inspect src/app/main.py", session_id="session-main"))
    request = model_client.requests[0]

    assert {skill.name for skill in request.skills} == {"always-on", "python-only"}
    assert set(request.turn_context.available_skills) == {"always-on", "python-only"}
    visible = {entry.name: entry for entry in request.turn_context.available_invocations}
    assert set(visible) == {"always-on", "python-only", "host-only"}
    assert visible["host-only"].user_invocable is True
    assert visible["host-only"].model_invocable is False


def test_runtime_prompt_metadata_applies_execution_policy_to_invocation_view(tmp_path: Path) -> None:
    model_client = FakeModelClient(
        [
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-policy"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "done"}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ]
        ]
    )
    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            model_client=model_client,
            builtins=BuiltinPackConfig(
                agents_enabled=False,
                skills_enabled=False,
                extra_agents=[
                    AgentDefinition(
                        name="main-router",
                        description="router",
                        prompt="route",
                    )
                ],
                extra_skills=[
                    SkillDefinition(
                        name="alpha",
                        description="Alpha",
                        content="alpha",
                        origin=_origin("alpha"),
                    ),
                    SkillDefinition(
                        name="beta",
                        description="Beta",
                        content="beta",
                        origin=_origin("beta"),
                    ),
                ],
            ),
        )
    )
    policy = ExecutionPolicyState(
        ExecutionPolicy(
            tool_pool=(),
            skill_pool=(runtime.kernel.skill_registry.get("alpha"),),
            permission_context=PermissionContext(session_id="session-policy"),
        )
    )

    asyncio.run(
        runtime.run_prompt(
            "Review the workspace",
            session_id="session-policy",
            metadata={"execution_policy_state": policy},
        )
    )
    request = model_client.requests[0]

    assert {skill.name for skill in request.skills} == {"alpha"}
    assert set(request.turn_context.available_skills) == {"alpha"}
    assert {entry.name for entry in request.turn_context.available_invocations} == {"alpha"}


def test_session_and_runtime_query_surfaces_return_visible_invocations(tmp_path: Path) -> None:
    docs_path = tmp_path / "docs" / "reference" / "guide.md"
    docs_path.parent.mkdir(parents=True)
    docs_path.write_text("guide", encoding="utf-8")
    model_client = FakeModelClient(
        [
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-session"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "done"}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ]
        ]
    )
    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            model_client=model_client,
            builtins=BuiltinPackConfig(
                agents_enabled=False,
                skills_enabled=False,
                extra_agents=[
                    AgentDefinition(
                        name="main-router",
                        description="router",
                        prompt="route",
                    )
                ],
                extra_skills=[
                    SkillDefinition(
                        name="docs-helper",
                        description="Docs only",
                        content="docs",
                        paths=("docs/**/*.md",),
                        origin=_origin("docs-helper"),
                    )
                ],
            ),
        )
    )
    session = runtime.create_session(session_id="session-query", cwd=tmp_path)
    asyncio.run(session.start())
    session.enqueue_event(
        InboundEvent(
            InboundEventType.USER_PROMPT,
            "Review the attachment",
            metadata={
                "attachments": [
                    {"name": "guide.md", "path": str(docs_path)},
                ]
            },
        )
    )
    asyncio.run(session.run_until_idle())

    session_visible = {entry.name for entry in session.visible_invocations()}
    runtime_visible = {entry.name for entry in runtime.visible_invocations(session)}
    diagnostics = {entry.name: entry for entry in runtime.invocation_diagnostics(session)}

    assert session_visible == {"docs-helper"}
    assert runtime_visible == {"docs-helper"}
    assert diagnostics["docs-helper"].path_match_state == InvocationPathMatchState.MATCHED


def test_observed_paths_activate_skills_and_preserve_policy_narrowing(tmp_path: Path) -> None:
    observed = tmp_path / "src" / "app" / "main.py"
    observed.parent.mkdir(parents=True)
    observed.write_text("print('ok')", encoding="utf-8")
    registry = SkillRegistry()
    registry.register(
        SkillDefinition(
            name="python-review",
            description="Python review",
            content="review",
            paths=("src/**/*.py",),
            allowed_tools=("read",),
            origin=_origin("python-review"),
        )
    )
    engine = TurnEngine(
        model_client=FakeModelClient([]),
        tool_registry=ToolRegistry(),
        skill_registry=registry,
    )

    catalog = engine.resolve_invocation_catalog(
        session_id="session",
        turn_id="turn",
        cwd=tmp_path,
        messages=(
            RuntimeMessage(
                message_id="tool-result",
                role=MessageRole.USER,
                content="{}",
                metadata={"observed_paths": [str(observed)]},
            ),
        ),
    )
    diagnostics = catalog.diagnostics_for("python-review")

    assert {entry.capability.name for entry in catalog.visible} == {"python-review"}
    assert diagnostics.path_match_state == InvocationPathMatchState.MATCHED
    assert diagnostics.narrowed_by_policy["allowed_tools"] == ("read",)


def test_placeholder_providers_integrate_with_invocation_registry(tmp_path: Path) -> None:
    slash = InvocationDefinition(
        name="slash-review",
        source_kind=InvocationSourceKind.SLASH_COMMAND,
        description="Slash review",
        execution_policy=InvocationExecutionPolicy(
            target_kind=InvocationTargetKind.SLASH_COMMAND,
            target_name="/review",
        ),
    )
    plugin = InvocationDefinition(
        name="plugin-review",
        source_kind=InvocationSourceKind.PLUGIN_COMMAND,
        description="Plugin review",
        execution_policy=InvocationExecutionPolicy(
            target_kind=InvocationTargetKind.PLUGIN_COMMAND,
            target_name="plugin.review",
        ),
    )
    prompt = InvocationDefinition(
        name="mcp-review",
        source_kind=InvocationSourceKind.MCP_PROMPT,
        description="MCP review",
        execution_policy=InvocationExecutionPolicy(
            target_kind=InvocationTargetKind.MCP_PROMPT,
            target_name="mcp.review",
        ),
    )
    registry = InvocationRegistry(
        (
            SlashCommandInvocationProvider((slash,)),
            PluginCommandInvocationProvider((plugin,)),
            McpPromptInvocationProvider((prompt,)),
        )
    )

    catalog = registry.resolve(
        InvocationResolutionContext(
            session_id="session",
            turn_id="turn",
            cwd=tmp_path.resolve(),
            workspace_roots=(tmp_path.resolve(),),
        )
    )
    assert {entry.capability.name for entry in catalog.visible} == {
        "slash-review",
        "plugin-review",
        "mcp-review",
    }


def test_invocation_registry_resolves_same_priority_conflicts_deterministically() -> None:
    slash = InvocationDefinition(
        name="review",
        source_kind=InvocationSourceKind.SLASH_COMMAND,
        description="Slash review",
        execution_policy=InvocationExecutionPolicy(
            target_kind=InvocationTargetKind.SLASH_COMMAND,
            target_name="/review",
        ),
        origin=DefinitionOrigin(DefinitionSource.USER, path=Path("/tmp/z-review")),
    )
    plugin = InvocationDefinition(
        name="review",
        source_kind=InvocationSourceKind.PLUGIN_COMMAND,
        description="Plugin review",
        execution_policy=InvocationExecutionPolicy(
            target_kind=InvocationTargetKind.PLUGIN_COMMAND,
            target_name="plugin.review",
        ),
        origin=DefinitionOrigin(DefinitionSource.USER, path=Path("/tmp/a-review")),
    )

    first = InvocationRegistry(
        (
            SlashCommandInvocationProvider((slash,)),
            PluginCommandInvocationProvider((plugin,)),
        )
    )
    second = InvocationRegistry(
        (
            PluginCommandInvocationProvider((plugin,)),
            SlashCommandInvocationProvider((slash,)),
        )
    )

    assert first.definitions()[0].origin.label == "/tmp/a-review"
    assert second.definitions()[0].origin.label == "/tmp/a-review"
    assert any(diag.code == "invocation_definition_conflict" for diag in first.diagnostics())
    assert any(diag.code == "invocation_definition_conflict" for diag in second.diagnostics())
