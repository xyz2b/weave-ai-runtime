# Use Cases

WeaveRT is designed for teams that need more than a single assistant prompt, but less than a fully custom orchestration stack.

## Who is this for?

- Repository visitors deciding what WeaveRT is and whether it fits their product or workflow.

## Prerequisites

- None. This layer is meant to be readable right after the root `../../README.md`.

Common fits:

- Coding assistant
  - workspace inspection, edit loops, verification, review, and approvals
  - see `../guides/use-scenario-packs.md` and `../../examples/apps/code_assistant/README.md`
- Chat or research assistant
  - retrieval, web, memory, and multi-step response flows
  - see `../../packages/product-kits/chat/README.md`
- Local assistant
  - host-owned permissions, shell or OS actions, and durable session state
  - see `../../packages/product-kits/local-assistant/README.md`
- Embedded runtime in an app or service
  - bind the runtime into your own host, routes, stores, and control plane
  - see `../guides/bind-a-host.md`

Good reasons to choose WeaveRT:

- you need session and turn ownership to stay explicit
- you want tools, agents, and skills to be separate extension types
- you want to compose first-party or app-local packages without losing control of the host
- you want the same runtime model to work for offline tests and live provider-backed runs

Less ideal fits:

- you only need a single fixed prompt and no runtime lifecycle
- you do not need durable state, permissions, or host integration
- you want a hosted product instead of an embeddable framework

Next reading:

- `design-principles.md`
- `../concepts/packages-and-scenario-packs.md`
- `../../examples/README.md`

## Next step

- Move to `../getting-started/quickstart.md` if one of these scenarios matches what you want to build.
- Read `design-principles.md` if you are evaluating the tradeoffs behind the runtime model.
- Jump to `../guides/use-scenario-packs.md` when you already know you need a product-profile path.

## See also

- `what-is-weavert.md`
- `design-principles.md`
- `../getting-started/quickstart.md`
- `../guides/use-scenario-packs.md`
