# What Is WeaveRT?

WeaveRT is a composable AI runtime framework for building agent systems.
It provides a stable runtime core and a clear set of extension surfaces for tools, agents, skills, hosts, permissions, memory, workflow packages, and scenario packs.

## Who is this for?

- Repository visitors deciding what WeaveRT is and whether it fits their product or workflow.

## Prerequisites

- None. This layer is meant to be readable right after the root `../../README.md`.

What WeaveRT is:

- a runtime model you can embed into CLI, SDK, worker, or app shells
- a framework for composing agent capabilities without hiding system ownership
- a path from small project-local workflows to richer product-shaped integrations

What WeaveRT is not:

- a single hard-coded assistant app
- a one-prompt demo that only works in one shell
- a framework that expects you to rewrite turn orchestration yourself

The core mental model is simple:

```text
Your App or Host
  -> RuntimeConfig
  -> RuntimeAssembly
  -> Session
  -> Turn Engine
  -> Tools / Skills / Agents / Memory / Hooks / Permissions
```

Start with the starter first.
Then learn the concepts that define each boundary.
Then move into guides, examples, and architecture only when you need them.

Next reading:

- `use-cases.md`
- `../getting-started/quickstart.md`
- `../concepts/runtime-model.md`

## Next step

- Read `use-cases.md` to map the framework onto real product shapes.
- Read `design-principles.md` to understand the architectural taste behind the runtime.
- Move to `../getting-started/quickstart.md` when you want to run the smallest project path.

## See also

- `../../README.md`
- `../README.md`
- `../getting-started/quickstart.md`
- `../concepts/runtime-model.md`
