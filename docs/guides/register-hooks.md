# Register Hooks

## Who is this for?

Users who want to inject logic into stable runtime lifecycle phases without rewriting the main runtime loop.

## Prerequisites

- a working runtime baseline
- familiarity with sessions or a bound host
- a specific lifecycle point you want to intercept or observe

## Stable versus advanced phases

The ordinary hook path should stay on stable public phases whenever possible.
Common stable phases include:

- `SessionStart`
- `SessionEnd`
- `PreToolUse`
- `PostToolUse`
- `PostToolUseFailure`
- `PreModelRequest`
- `PostModelResponse`
- `Stop`
- `Notification`
- `Elicitation`
- `ElicitationResult`

Advanced phases exist too, but they are not the default portability promise.
Use them only when the stable set is genuinely insufficient.

## The three authoring levels

The public hook surface is easiest to reason about in three layers:

- simple layered registrars
  - `runtime.hooks`, `bound.hooks`, `session.hooks`
- typed layer
  - phase-aware callback plus explicit effect intent
- raw layer
  - direct `HookRegistrationRequest` control

Start simple first.
Only move to typed or raw registration when you need more explicit effect or scope control.

## Minimal session-scoped example

```python
from weavert.hooks import HookDispatchTraceQuery, HookInventoryQuery, match_tool, rewrite_input

handle = session.hooks.on_pre_tool_use(
    lambda _payload: rewrite_input({"value": "rewritten"}),
    match=match_tool("echo"),
    effects=(rewrite_input,),
)

inventory = session.list_hooks(HookInventoryQuery(phase="PreToolUse"))
traces = session.list_hook_dispatch_traces(HookDispatchTraceQuery(phase="PreToolUse", limit=20))
```

This is the best first pattern when you want one small, inspectable runtime hook.

## Pick the right registration source

### Runtime-level template registration

Use this when every future session should inherit the hook by default.

### Bound-host registration

Use this when the host wants to inject policy or behavior into sessions it owns.
This is a good fit for enterprise routing, approvals, or audit posture.

### Session registration

Use this when the behavior should last for one session only.

### Turn-owned advanced registration

Use this only when the behavior should live for the current turn and nowhere else.

### Skill hooks

Use this when the hook should travel with a reusable workflow step.

## How to inspect and debug hook behavior

After registration, verify both inventory and dispatch:

- `list_hooks(...)`
  - confirms phase, source, scope, and activation state
- `list_hook_dispatch_traces(...)`
  - confirms matching, blocking, ignored effects, and applied outcomes

If a hook effect is not supported for the phase, it should show up as ignored rather than silently succeeding.

## When not to use agent-owned hooks

Agent-owned hooks are not the ordinary recommended v1 path.
Prefer:

- skill hooks
- session hooks
- bound-host hooks
- runtime-config hook registration

## Expected result

You can register, observe, and debug hook behavior through stable runtime surfaces.

## Next step

Run `python3 -B -m examples.hooks.session_register_hook_demo` or `python3 -B -m examples.hooks.host_registered_hook_demo`.

## See also

- `extend-the-control-plane.md`
- `testing-and-observability.md`
- `../reference/hook-registration.md`
- `../deep-dives/weavert-hook-configuration-platform.md`
