# Runtime Hook Configuration Platform

The runtime now exposes a public hook configuration platform on top of the session-scoped `HookBus`.

## Public Phase Catalog

`kernel public`

- `SessionStart`
- `UserPromptSubmit`
- `PreToolUse`
- `PostToolUse`
- `PostToolUseFailure`
- `Stop`
- `SubagentStop`
- `SessionEnd`
- `Notification`
- `Elicitation`
- `ElicitationResult`
- `PreCompact`
- `PostCompact`

`control-plane public`

- `PreContextAssemble`
- `PostContextAssemble`
- `PreModelRequest`
- `PostModelResponse`
- `RecoveryDecision`

Any unlisted phase is treated as `internal-only` and is rejected by the public registration APIs.

## Public API Shapes

```python
from runtime.hooks import (
    HookDispatchTraceQuery,
    HookHandlerKind,
    HookHandlerManifest,
    HookInventoryQuery,
    HookRegistrationRequest,
    HookRegistrationScope,
    HookScopeLifetime,
)

handle = session.register_hook(
    HookRegistrationRequest(
        phase="PreToolUse",
        match={"target": "deploy"},
        scope=HookRegistrationScope(
            lifetime=HookScopeLifetime.TURN,
            session_id=session.state.session_id,
            turn_id=session.state.active_turn_id,
        ),
        handler=HookHandlerManifest(
            kind=HookHandlerKind.CALLBACK,
            callback=lambda _payload: {"continue_execution": False},
        ),
    )
)

inventory = session.list_hooks(HookInventoryQuery(phase="PreToolUse"))
traces = session.list_hook_dispatch_traces(HookDispatchTraceQuery(phase="PreToolUse", limit=20))
```

`handle.activation_state` exposes `pending_activation`, `active`, `released`, `expired`, or `rejected`. `handle.release()` is idempotent.

## Runtime Config Baseline

Runtime config hook documents use the canonical `hooks.handlers` + `hooks.registrations` authoring shape and materialize as session-owned entries when a session starts.

```python
from runtime.runtime_kernel import RuntimeConfig, assemble_runtime

runtime = assemble_runtime(
    RuntimeConfig(
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
        }
    )
)

runtime.bind_hook_callback(
    "runtime_context_override",
    lambda _payload: {"request_override": {"requested_model_route": "runtime-route"}},
)
```

## Host API Template

```python
handle = host.register_hook(
    HookRegistrationRequest(
        phase="PreModelRequest",
        scope=HookRegistrationScope(lifetime=HookScopeLifetime.SESSION_TEMPLATE),
        handler=HookHandlerManifest(
            kind=HookHandlerKind.CALLBACK,
            callback=lambda _payload: {"request_override": {"requested_model": "enterprise-model"}},
        ),
        contract={"effect_fields": ["request_override", "metadata"]},
    )
)
```

## Legacy Definition Compatibility

Legacy phase-keyed definitions are still accepted and are normalized before activation:

```yaml
hooks:
  PreToolUse:
    matcher: echo
    effect:
      updated_input:
        value: rewritten
```

The canonical declarative shape is still preferred for new surfaces.

## Stop / Recovery Approval Flow

`Stop` hooks can block continuation and stage a resumable request override. `RecoveryDecision` hooks can then resume execution through the canonical recovery path.

```python
runtime.bind_hook_callback(
    "runtime_stop_guard",
    lambda _payload: {
        "continue_execution": False,
        "stop_disposition": "block_session",
        "request_override": {"max_output_tokens": 1024},
    },
)

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
    )
)
```

The corresponding dispatch traces expose `matched_registrations`, `blocked_registrations`, `ignored_effects`, `winner_summary`, and `applied_outcome`.

## External Handlers

The public manifest model supports `callback`, `http`, `command`, `agent`, and `prompt`. External handlers are denied by default and must be explicitly allowed through `HookBus.set_handler_policy(...)`.

```python
runtime.services.hook_bus.set_handler_policy("http", allowed=True, phase="PostToolUse")
```

When policy blocks an external handler, the dispatch trace records a `blocked_registrations` entry with reason `policy_denied`.
