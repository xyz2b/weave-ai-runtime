# Bind a Host

## Who is this for?

Users embedding WeaveRT into a CLI, SDK, service, or app shell that needs lifecycle control and runtime event ownership.

## Prerequisites

- a working runtime baseline
- `packages/framework-packs/integrations/hosts-reference` installed if you want the reference host types
- a reason to own approvals, notifications, or turn-event rendering

## When you actually need a host

Stay on plain `RuntimeAssembly` helpers when you only need one-shot or headless workflow execution.
Bind a host when you need:

- approval UX
- elicitation
- longer-lived session control
- turn-event rendering
- app-owned local commands or shell behavior

## Minimal binding example

```python
from pathlib import Path

from weavert import RuntimeConfig, assemble_runtime
from weavert_hosts_reference import SdkHostRuntime

runtime = assemble_runtime(RuntimeConfig.for_ordinary_workflow(Path.cwd()))
host = SdkHostRuntime(name="sdk")
bound = runtime.bind_host(host)
```

For longer-lived integrations, treat the bound runtime as the host-owned lifecycle surface and shut it down explicitly.

## Preferred grouped surfaces

Once bound, prefer the grouped surfaces over compatibility-style flat helpers:

- `bound.prompts`
- `bound.sessions`
- `bound.hooks`
- `bound.inspection`
- `bound.work`

## Lifecycle ownership

A useful mental model is:

- the host owns startup, ready, shutdown, approvals, and presentation
- the session still owns transcript continuity
- the turn engine still owns one execution cycle

The runtime should not force you to rebuild those layers in your app shell.

## Common host concerns

Good host responsibilities include:

- permission prompts
- notifications and progress rendering
- mapping runtime events into app-specific UI or logs
- local commands that should not spend model turns

## Expected result

Your host owns lifecycle, approvals, and event presentation while the runtime continues to own session and turn orchestration.

## Next step

Validate the seam with `python3 -B -m examples.hosts.minimal_host_bound_demo`.

## See also

- `../concepts/hosts-permissions-memory.md`
- `extend-the-control-plane.md`
- `register-hooks.md`
- `testing-and-observability.md`
- `../deep-dives/weavert-control-plane-extension-guide.md`
