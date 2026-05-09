# Design Principles

These principles shape the public documentation path and the runtime itself.

## Who is this for?

- Repository visitors deciding what WeaveRT is and whether it fits their product or workflow.

## Prerequisites

- None. This layer is meant to be readable right after the root `../../README.md`.

## Runtime over prompt

WeaveRT treats prompts as one ingredient inside a broader execution model.
Sessions, turns, tools, agents, skills, permissions, and memory remain first-class runtime concerns.

## Clear ownership boundaries

The runtime owns orchestration.
The host owns product UX, approvals, and presentation.
Packages can contribute capability and guidance, but they do not silently take over the host.

## Composition over monoliths

Tools, agents, skills, packages, and hosts have different jobs.
Keeping those seams separate makes it easier to start small and extend safely.

## Stable surfaces first

The recommended path is:

1. starter scaffold
2. project-local `.weavert/` definitions
3. task-specific guides
4. examples for validation
5. host binding and package composition

## Visibility over magic

Permissions, route failures, package activation, diagnostics, and durable state should stay inspectable.
Framework users should not have to guess who owns a decision.

Next reading:

- `../concepts/runtime-model.md`
- `../architecture/overview.md`

## Next step

- Read `../concepts/runtime-model.md` to connect the principles to the stable runtime surfaces.
- Move to `../architecture/overview.md` when you want the implementation-oriented layer map.

## See also

- `what-is-weavert.md`
- `use-cases.md`
- `../concepts/runtime-model.md`
- `../architecture/overview.md`
