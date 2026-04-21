import asyncio
from pathlib import Path

from runtime.contracts import MessageRole
from runtime.elicitation import ElicitationRequest
from runtime.definitions import ToolDefinition
from runtime.hooks import (
    HookActivationState,
    HookBus,
    HookDispatchTraceQuery,
    HookHandlerKind,
    HookHandlerManifest,
    HookInventoryQuery,
    HookRegistrationRequest,
    HookRegistrationScope,
    HookScopeLifetime,
    HookSourceKind,
    PostToolUseFailurePayload,
    PreToolUsePayload,
    RuntimeHookPhase,
)
from runtime.registries import ToolRegistry
from runtime.runtime_kernel import RuntimeConfig, assemble_runtime
from runtime.runtime_services import RuntimeServices
from runtime.tool_runtime import ToolCall, ToolContext, ToolScheduler
from runtime.turn_engine import ModelStreamEvent, ModelStreamEventType

from .runtime_protocol_harness import RequestCaptureModelClient


def test_public_phase_registry_rejects_internal_phase() -> None:
    bus = HookBus()

    handle = bus.register_request(
        HookRegistrationRequest(
            phase="InternalOnlyPhase",
            scope=HookRegistrationScope(
                lifetime=HookScopeLifetime.SESSION,
                session_id="session-a",
            ),
            handler=HookHandlerManifest(kind=HookHandlerKind.CALLBACK, callback=lambda _payload: None),
        ),
        source_kind=HookSourceKind.RUNTIME_CONFIG,
        owner="runtime:test",
        source_ref="runtime:test",
        session_id="session-a",
    )

    inventory = bus.list_hooks(HookInventoryQuery(session_id="session-a"))

    assert handle.activation_state == HookActivationState.REJECTED
    assert inventory[0].activation_state == HookActivationState.REJECTED
    assert inventory[0].phase == "InternalOnlyPhase"


def test_turn_api_precedence_wins_for_replace_style_fields() -> None:
    bus = HookBus()
    bus.register_document(
        hooks={
            "PreToolUse": {
                "matcher": "deploy",
                "effect": {"updated_input": {"value": "definition"}},
            }
        },
        source_kind=HookSourceKind.DEFINITION,
        owner="definition:rewrite",
        session_id="session-a",
        turn_id="turn-a",
        default_scope_lifetime=HookScopeLifetime.TURN,
    )
    turn_handle = bus.register_request(
        HookRegistrationRequest(
            phase=RuntimeHookPhase.PRE_TOOL_USE.value,
            match={"target": "deploy"},
            scope=HookRegistrationScope(
                lifetime=HookScopeLifetime.TURN,
                session_id="session-a",
                turn_id="turn-a",
            ),
            handler=HookHandlerManifest(
                kind=HookHandlerKind.CALLBACK,
                callback=lambda _payload: {"updated_input": {"value": "turn-api"}},
            ),
        ),
        source_kind=HookSourceKind.TURN_API,
        owner="turn:rewrite",
        source_ref="turn:rewrite",
        session_id="session-a",
        turn_id="turn-a",
    )

    result = asyncio.run(
        bus.dispatch(
            "session-a",
            PreToolUsePayload(
                session_id="session-a",
                turn_id="turn-a",
                tool_name="deploy",
                tool_input={"value": "original"},
            ),
        )
    )

    assert result.updated_input == {"value": "turn-api"}
    assert result.winner_summary["updated_input"]["winner_registration_id"] == turn_handle.registration_id
    trace = bus.list_hook_dispatch_traces(
        HookDispatchTraceQuery(session_id="session-a", phase=RuntimeHookPhase.PRE_TOOL_USE.value)
    )[0]
    assert trace.winner_summary["updated_input"]["winner_registration_id"] == turn_handle.registration_id


def test_request_override_propagates_from_post_context_to_pre_model_and_materialized_templates(
    tmp_path: Path,
) -> None:
    model_client = RequestCaptureModelClient(
        [
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-1"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "reply"}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ]
        ]
    )
    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            model_client=model_client,
            hooks={
                "handlers": {
                    "runtime_context_override": {
                        "kind": "callback",
                        "binding": "runtime_context_override",
                    }
                },
                "registrations": [
                    {
                        "phase": "PostContextAssemble",
                        "handler": {"ref": "runtime_context_override"},
                        "contract": {"effect_fields": ["request_override", "metadata"]},
                    }
                ],
            },
        )
    )
    runtime.bind_hook_callback(
        "runtime_context_override",
        lambda _payload: {
            "request_override": {
                "requested_model_route": "runtime-route",
            }
        },
    )
    session = runtime.create_session(session_id="hook-request-override")
    session.register_hook(
        HookRegistrationRequest(
            phase="PreModelRequest",
            handler=HookHandlerManifest(
                kind=HookHandlerKind.CALLBACK,
                callback=lambda _payload: {
                    "request_override": {"requested_model": "session-model"},
                },
            ),
            contract={"effect_fields": ["request_override", "metadata"]},
        )
    )

    produced = asyncio.run(runtime._run_prompt_in_session(session, "hello"))

    request = model_client.requests[0]
    assert produced[-1].role == MessageRole.ASSISTANT
    assert request.requested_model_route == "runtime-route"
    assert request.model == "session-model"
    assert request.metadata["request_override"]["field_sources"]["requested_model_route"] != ""
    assert request.metadata["request_override"]["field_sources"]["requested_model"] != ""
    traces = session.list_hook_dispatch_traces(
        HookDispatchTraceQuery(phase="PreModelRequest")
    )
    assert traces[0].winner_summary["request_override"]["field_sources"]["requested_model"] != ""


def test_tool_denial_and_elicitation_metadata_correlate_to_dispatch_traces(tmp_path: Path) -> None:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="deploy",
            description="deploy",
            input_schema={
                "type": "object",
                "properties": {"value": {"type": "string"}},
                "required": ["value"],
                "additionalProperties": False,
            },
            execute=lambda tool_input, _context: {"value": tool_input["value"]},
        )
    )
    services = RuntimeServices()
    services.hook_bus.register_request(
        HookRegistrationRequest(
            phase="PreToolUse",
            match={"target": "deploy"},
            scope=HookRegistrationScope(
                lifetime=HookScopeLifetime.TURN,
                session_id="session-tool",
                turn_id="turn-tool",
            ),
            handler=HookHandlerManifest(
                kind=HookHandlerKind.CALLBACK,
                callback=lambda _payload: {"continue_execution": False, "notifications": ("denied",)},
            ),
        ),
        source_kind=HookSourceKind.SESSION_API,
        owner="session:tool-guard",
        source_ref="tool-guard",
        session_id="session-tool",
        turn_id="turn-tool",
    )
    scheduler = ToolScheduler(registry)
    context = ToolContext(
        session_id="session-tool",
        turn_id="turn-tool",
        agent_name="main-router",
        cwd=tmp_path,
        tool_registry=registry,
        runtime_services=services,
    )

    result = asyncio.run(
        scheduler.run(
            [ToolCall(call_id="call-1", tool_name="deploy", tool_input={"value": "now"})],
            context,
        )
    )[0]

    assert result.status.value == "denied"
    assert result.metadata["continuation_blocked"] is True
    tool_trace = services.hook_bus.list_hook_dispatch_traces(
        HookDispatchTraceQuery(session_id="session-tool", phase="PreToolUse")
    )[0]
    assert tool_trace.dispatch_id == result.metadata["hook_dispatch_id"]
    assert tool_trace.applied_outcome["continuation_blocked"] is True

    services.hook_bus.register_request(
        HookRegistrationRequest(
            phase="Elicitation",
            scope=HookRegistrationScope(
                lifetime=HookScopeLifetime.SESSION,
                session_id="session-tool",
            ),
            handler=HookHandlerManifest(
                kind=HookHandlerKind.CALLBACK,
                callback=lambda _payload: {"elicitation_result": {"response": "approved"}},
            ),
        ),
        source_kind=HookSourceKind.TURN_API,
        owner="turn:elicitation",
        source_ref="turn:elicitation",
        session_id="session-tool",
    )

    runtime_context = type("HookCtx", (), {"hook_bus": services.hook_bus})()
    response = asyncio.run(
        services.elicitation.request(
            ElicitationRequest(
                session_id="session-tool",
                turn_id="turn-tool",
                prompt="Proceed?",
            ),
            runtime_context=runtime_context,
        )
    )

    assert response.source == "hook"
    assert response.metadata["satisfied_by_hook"] is True
    elicitation_trace = services.hook_bus.list_hook_dispatch_traces(
        HookDispatchTraceQuery(session_id="session-tool", phase="Elicitation")
    )[0]
    assert elicitation_trace.dispatch_id == response.metadata["hook_dispatch_id"]


def test_unsupported_effect_fields_are_ignored_with_diagnostics() -> None:
    bus = HookBus()
    bus.register_request(
        HookRegistrationRequest(
            phase="PostToolUseFailure",
            scope=HookRegistrationScope(
                lifetime=HookScopeLifetime.SESSION,
                session_id="session-a",
            ),
            handler=HookHandlerManifest(
                kind=HookHandlerKind.CALLBACK,
                callback=lambda _payload: {
                    "request_override": {"requested_model": "should-be-ignored"},
                    "notifications": ("still-runs",),
                },
            ),
        ),
        source_kind=HookSourceKind.DEFINITION,
        owner="definition:failure-hook",
        source_ref="definition:failure-hook",
        session_id="session-a",
    )

    result = asyncio.run(
        bus.dispatch(
            "session-a",
            PostToolUseFailurePayload(
                session_id="session-a",
                turn_id="turn-a",
                tool_name="deploy",
                tool_input={"value": "x"},
                error_message="boom",
            ),
        )
    )

    assert result.request_override is None
    assert result.notifications == ("still-runs",)
    assert result.ignored_effects[0].field == "request_override"


def test_policy_blocked_external_handlers_are_visible_in_dispatch_trace() -> None:
    bus = HookBus()
    bus.register_request(
        HookRegistrationRequest(
            phase="PostToolUse",
            scope=HookRegistrationScope(
                lifetime=HookScopeLifetime.SESSION,
                session_id="session-a",
            ),
            handler=HookHandlerManifest(
                kind=HookHandlerKind.HTTP,
                endpoint="https://example.invalid/hook",
                timeout_ms=100,
            ),
        ),
        source_kind=HookSourceKind.HOST_API,
        owner="host:audit",
        source_ref="host:audit",
        session_id="session-a",
    )

    result = asyncio.run(
        bus.dispatch(
            "session-a",
            {
                "phase": RuntimeHookPhase.POST_TOOL_USE.value,
                "turn_id": "turn-a",
                "tool_name": "deploy",
                "tool_input": {"value": "ship"},
                "tool_result": {"ok": True},
            },
        )
    )

    assert result.blocked_registrations[0].reason == "policy_denied"
    trace = bus.list_hook_dispatch_traces(
        HookDispatchTraceQuery(session_id="session-a", phase="PostToolUse")
    )[0]
    assert trace.blocked_registrations[0].reason == "policy_denied"
    assert trace.blocked_registrations[0].handler_kind == HookHandlerKind.HTTP


def test_stop_and_recovery_hooks_resume_with_persisted_override(tmp_path: Path) -> None:
    model_client = RequestCaptureModelClient(
        [
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-stop-1"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "first"}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ],
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-stop-2"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "second"}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ],
        ]
    )
    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            model_client=model_client,
            hooks={
                "handlers": {
                    "runtime_stop_guard": {
                        "kind": "callback",
                        "binding": "runtime_stop_guard",
                    }
                },
                "registrations": [
                    {
                        "phase": "Stop",
                        "handler": {"ref": "runtime_stop_guard"},
                        "contract": {
                            "effect_fields": ["continue_execution", "stop_disposition", "request_override", "metadata"]
                        },
                    }
                ],
            },
        )
    )
    runtime.bind_hook_callback(
        "runtime_stop_guard",
        lambda _payload: {
            "continue_execution": False,
            "stop_disposition": "block_session",
            "request_override": {"max_output_tokens": 1024},
        },
    )
    session = runtime.create_session(session_id="stop-recovery")
    session.register_hook(
        HookRegistrationRequest(
            phase="RecoveryDecision",
            handler=HookHandlerManifest(
                kind=HookHandlerKind.CALLBACK,
                callback=lambda _payload: {
                    "continue_execution": True,
                    "injected_messages": ["Approval received"],
                },
            ),
            contract={"effect_fields": ["continue_execution", "injected_messages", "metadata"]},
            once=True,
        )
    )

    produced = asyncio.run(runtime._run_prompt_in_session(session, "resume"))

    assert len(model_client.requests) == 2
    assert model_client.requests[1].max_output_tokens == 1024
    assert any(message.text == "Approval received" for message in produced)
    traces = session.list_hook_dispatch_traces(
        HookDispatchTraceQuery(phase="RecoveryDecision")
    )
    assert traces[0].applied_outcome["continuation_blocked"] is False
