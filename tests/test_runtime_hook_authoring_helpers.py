import asyncio
from pathlib import Path

from weavert.hooks import (
    HookActivationState,
    HookBus,
    HookDispatchTraceQuery,
    HookEffectClass,
    HookEffectContract,
    HookHandlerKind,
    HookHandlerManifest,
    HookInventoryQuery,
    HookMatch,
    HookRegistrationRequest,
    HookRegistrationScope,
    HookScopeLifetime,
    HookStopDisposition,
    HookSourceKind,
    PreToolUsePayload,
    StopPayload,
    block_execution,
    match_tool,
    match_tool_pattern,
    on_stop,
    on_pre_tool_use,
    respond_to_elicitation,
    rewrite_input,
)
from weavert.runtime_kernel import RuntimeConfig, assemble_runtime


def test_helper_surface_builds_ordinary_hook_registration_request() -> None:
    request = on_pre_tool_use(
        rewrite_input({"value": "helper"}),
        match=match_tool("deploy"),
    )

    assert request == HookRegistrationRequest(
        phase="PreToolUse",
        match=HookMatch(target="deploy"),
        scope=HookRegistrationScope(lifetime=HookScopeLifetime.SESSION),
        handler=HookHandlerManifest(
            kind=HookHandlerKind.CALLBACK,
            static_effect=rewrite_input({"value": "helper"}),
        ),
        contract=HookEffectContract(
            effect_classes=(HookEffectClass.TRANSFORM,),
            effect_fields=("updated_input",),
        ),
    )


def test_helper_callback_request_dispatches_through_same_hook_bus_path() -> None:
    bus = HookBus()
    request = on_pre_tool_use(
        lambda payload: rewrite_input({"value": payload.tool_input["value"].upper()}),
        match=match_tool("deploy"),
        effects=(rewrite_input,),
    )

    handle = bus.register_request(
        request,
        source_kind=HookSourceKind.SESSION_API,
        owner="session:rewrite",
        source_ref="session:rewrite",
        session_id="session-a",
    )

    result = asyncio.run(
        bus.dispatch(
            "session-a",
            PreToolUsePayload(
                session_id="session-a",
                turn_id="turn-a",
                tool_name="deploy",
                tool_input={"value": "ship"},
            ),
        )
    )

    assert handle.activation_state == HookActivationState.ACTIVE
    assert result.updated_input == {"value": "SHIP"}
    assert result.winner_summary["updated_input"]["winner_registration_id"] == handle.registration_id
    trace = bus.list_hook_dispatch_traces(
        HookDispatchTraceQuery(session_id="session-a", phase="PreToolUse")
    )[0]
    assert trace.winner_summary["updated_input"]["winner_registration_id"] == handle.registration_id


def test_helper_callback_declarations_preserve_runtime_effect_metadata() -> None:
    bus = HookBus()
    handle = bus.register_request(
        on_pre_tool_use(
            lambda _payload: rewrite_input({"value": "SHIP"}, metadata={"source": "helper"}),
            match=match_tool("deploy"),
            effects=(rewrite_input,),
        ),
        source_kind=HookSourceKind.SESSION_API,
        owner="session:rewrite-metadata",
        source_ref="session:rewrite-metadata",
        session_id="session-a",
    )

    result = asyncio.run(
        bus.dispatch(
            "session-a",
            PreToolUsePayload(
                session_id="session-a",
                turn_id="turn-a",
                tool_name="deploy",
                tool_input={"value": "ship"},
            ),
        )
    )

    assert handle.activation_state == HookActivationState.ACTIVE
    assert result.updated_input == {"value": "SHIP"}
    assert result.metadata == {"source": "helper"}
    assert result.ignored_effects == ()


def test_helper_callback_declarations_preserve_runtime_stop_fields() -> None:
    bus = HookBus()
    handle = bus.register_request(
        on_stop(
            lambda _payload: block_execution(
                "blocked",
                stop_disposition=HookStopDisposition.CONTINUE_SAME_TURN,
                metadata={"source": "helper"},
            ),
            effects=(block_execution,),
        ),
        source_kind=HookSourceKind.SESSION_API,
        owner="session:stop-helper",
        source_ref="session:stop-helper",
        session_id="session-a",
    )

    result = asyncio.run(
        bus.dispatch(
            "session-a",
            StopPayload(session_id="session-a", turn_id="turn-a", reason="blocked-by-test"),
        )
    )

    assert handle.activation_state == HookActivationState.ACTIVE
    assert result.continue_execution is True
    assert result.notifications == ("blocked",)
    assert result.stop_disposition == HookStopDisposition.CONTINUE_SAME_TURN
    assert result.metadata == {"source": "helper"}
    assert result.ignored_effects == ()


def test_helper_generated_unsupported_effect_is_rejected_by_registration_validation() -> None:
    bus = HookBus()

    handle = bus.register_request(
        on_pre_tool_use(
            respond_to_elicitation({"response": "approved"}),
            match=match_tool("deploy"),
        ),
        source_kind=HookSourceKind.SESSION_API,
        owner="session:invalid-effect",
        source_ref="session:invalid-effect",
        session_id="session-a",
    )

    inventory = bus.list_hooks(
        HookInventoryQuery(
            session_id="session-a",
            activation_state=HookActivationState.REJECTED,
        )
    )

    assert handle.activation_state == HookActivationState.REJECTED
    assert inventory[0].phase == "PreToolUse"


def test_matcher_shortcuts_and_turn_scope_shortcut_behave_like_raw_requests() -> None:
    bus = HookBus()
    session_handle = bus.register_request(
        on_pre_tool_use(
            rewrite_input({"value": "session"}),
            match=match_tool_pattern("deploy*"),
        ),
        source_kind=HookSourceKind.SESSION_API,
        owner="session:pattern",
        source_ref="session:pattern",
        session_id="session-a",
    )
    turn_handle = bus.register_request(
        on_pre_tool_use(
            block_execution(),
            match=match_tool("deploy-prod"),
            scope="turn",
        ),
        source_kind=HookSourceKind.TURN_API,
        owner="turn:block",
        source_ref="turn:block",
        session_id="session-a",
        turn_id="turn-a",
    )

    matching_turn_result = asyncio.run(
        bus.dispatch(
            "session-a",
            PreToolUsePayload(
                session_id="session-a",
                turn_id="turn-a",
                tool_name="deploy-prod",
                tool_input={"value": "original"},
            ),
        )
    )
    other_turn_result = asyncio.run(
        bus.dispatch(
            "session-a",
            PreToolUsePayload(
                session_id="session-a",
                turn_id="turn-b",
                tool_name="deploy-prod",
                tool_input={"value": "original"},
            ),
        )
    )

    assert session_handle.activation_state == HookActivationState.ACTIVE
    assert turn_handle.activation_state == HookActivationState.ACTIVE
    assert matching_turn_result.continue_execution is False
    assert other_turn_result.updated_input == {"value": "session"}


def test_runtime_register_hook_accepts_helper_default_scope_for_template_surfaces(tmp_path: Path) -> None:
    runtime = assemble_runtime(RuntimeConfig(working_directory=tmp_path))

    handle = runtime.register_hook(
        on_pre_tool_use(
            rewrite_input({"value": "runtime-default"}),
            match=match_tool("deploy"),
        )
    )

    assert handle.activation_state == HookActivationState.PENDING_ACTIVATION
    assert handle.scope == HookRegistrationScope(lifetime=HookScopeLifetime.SESSION_TEMPLATE)

    session = runtime.create_session(session_id="helper-template-session", cwd=tmp_path)
    runtime.services.hook_bus.materialize_session("helper-template-session")
    inventory = session.list_hooks(HookInventoryQuery(phase="PreToolUse"))

    assert len(inventory) == 1
    assert inventory[0].activation_state == HookActivationState.ACTIVE
    assert inventory[0].scope.lifetime == HookScopeLifetime.SESSION
    assert inventory[0].parent_registration_id == handle.registration_id
