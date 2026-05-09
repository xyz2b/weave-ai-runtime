# Extend the Control Plane

## Who is this for?

Users who are no longer just adding tools, agents, or skills, and now need to shape runtime behavior through hosts, permissions, elicitation, hooks, context contributors, or dynamic capability refresh.

## Prerequisites

- a working runtime baseline
- comfort with `RuntimeConfig` and `RuntimeAssembly`
- a reason to change runtime behavior without rewriting the turn engine

## The first distinction: event hooks versus context contributors

Two extension types are easy to confuse, but they solve different problems.

- Hook bus registrations
  - react to a runtime phase such as `PreToolUse`, `Stop`, or `SessionEnd`
  - return hook effects
- context contributors
  - contribute prompt, private, or diagnostics data before request assembly
  - are package-owned sidecars, not HookBus events

A useful rule of thumb is:

- use hooks when you are reacting to lifecycle phases
- use context contributors when you are shaping the request context before the model call

## Choose the right control-plane seam

### Host

Use a host when your product needs:

- lifecycle ownership
- approval UX
- elicitation UX
- turn-event rendering
- app-local commands or app shell behavior

### Permissions

Use the permission path when a tool, shell action, or delegated workflow should remain explicitly mediated rather than silently executing.

### Elicitation

Use elicitation when the runtime needs structured human input instead of just a yes or no approval.

### Hooks

Use hooks when a stable lifecycle phase is the right injection point, such as rewriting tool input, blocking an operation, adjusting a model request, or observing stop behavior.

### Context contributors

Use context contributors when package-owned logic should add:

- prompt-visible fragments
- runtime-private fragments
- diagnostics

### Tool refresh

Use `tool_refresh_callback` when the visible capability pool should be refreshed dynamically at request time instead of staying fixed for the whole runtime lifecycle.

## Minimal host-binding integration

```python
from pathlib import Path

from weavert import RuntimeConfig, assemble_runtime
from weavert_hosts_reference import SdkHostRuntime

runtime = assemble_runtime(RuntimeConfig.for_ordinary_workflow(Path.cwd()))
host = SdkHostRuntime(name="sdk")
bound = runtime.bind_host(host)
```

Prefer the grouped bound surfaces:

- `bound.prompts`
- `bound.sessions`
- `bound.hooks`
- `bound.inspection`
- `bound.work`

## Permissions and elicitation posture

A simple mental model is:

- the runtime decides when permission or elicitation is needed
- the host may own how that interaction is presented
- the decision record should stay explicit and inspectable

Keep these concerns separate from prompt logic whenever possible.

## Context-contributor rules

Context contributors should preserve channel boundaries:

- prompt contributions for model-visible context
- private contributions for runtime-only state
- diagnostics contributions for inspection and debugging

Avoid mixing prompt-safe and runtime-private state into one undifferentiated payload.

## Tool refresh guidance

Reach for `tool_refresh_callback` when the visible tool set depends on changing environment or session conditions.
Avoid using it as a substitute for ordinary static tool discovery when a fixed project-local tool set is enough.

## Expected result

You extend runtime behavior through stable control-plane seams while keeping session and turn orchestration owned by the runtime.

## Next step

- For lifecycle injection, read `register-hooks.md`
- For host lifecycle and approvals, read `bind-a-host.md`
- For observability and validation, read `testing-and-observability.md`

## See also

- `bind-a-host.md`
- `register-hooks.md`
- `../concepts/hosts-permissions-memory.md`
- `../deep-dives/weavert-control-plane-extension-guide.md`
