# Hook Registration Reference

This page summarizes the stable vocabulary around public hook registration.

## Who is this for?

- Readers who already know the workflow and now need a stable lookup page.

## Prerequisites

- Read the matching guide or concept page first.
- Treat this page as a reference sheet, not the first-stop tutorial.

## Stable public phases

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

## Advanced public phases

- `UserPromptSubmit`
- `SubagentStop`
- `PreCompact`
- `PostCompact`
- `PreContextAssemble`
- `PostContextAssemble`
- `RecoveryDecision`

Use advanced phases only when the stable set is not enough for your integration.

## Common registration scopes

- `session-template`
  - template registration that later materializes into concrete sessions
- `session`
  - active for the session lifetime
- `turn`
  - short-lived registration for the current turn

## Public registration layers

- simple layered registrars
  - `runtime.hooks`, `bound.hooks`, `session.hooks`
- typed registration layer
  - explicit effect intent with phase-aware callbacks
- raw registration layer
  - direct canonical request control

## Handler kinds

Stable public handler kind:

- `callback`

Advanced or package-specific handler kinds may include:

- `http`
- `command`
- `agent`
- `prompt`

Ordinary integrations should assume `callback` is the portable default.

## Activation-state vocabulary

Common activation states include:

- `pending_activation`
- `active`
- `released`
- `expired`
- `rejected`

## Inventory and dispatch inspection

Useful inspection helpers include:

- `HookInventoryQuery`
- `HookDispatchTraceQuery`

They help answer:

- which registrations exist
- which ones matched
- which effects were ignored
- what outcome was actually applied

## Next step

- Return to `../guides/register-hooks.md` for the step-by-step authoring path.
- Use `../guides/testing-and-observability.md` when the next task is proving a hook matched and applied correctly.

## See also

- `../guides/register-hooks.md`
- `../guides/extend-the-control-plane.md`
- `../guides/testing-and-observability.md`
- `../deep-dives/weavert-hook-configuration-platform.md`
