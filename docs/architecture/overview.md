# Architecture Overview

This page answers one question: what are the main layers of WeaveRT, and what does each one own?

```text
Your App / Host
  -> RuntimeConfig
  -> RuntimeAssembly
  -> SessionController
  -> TurnEngine
  -> Tools / Skills / Agents / Memory / Hooks / Permissions
```

## Who is this for?

- Readers evaluating how the runtime is assembled, executed, and persisted under the hood.

## Prerequisites

- Read `../concepts/runtime-model.md` first.
- Use the relevant concept pages as vocabulary support before treating this as the deeper architecture layer.

## Two planes: control and execution

A helpful way to read the architecture is to separate two planes:

- control plane
  - hooks
  - permissions
  - elicitation
  - memory
  - compaction
  - host bridge
  - task and job surfaces
- execution plane
  - model invocation
  - tool orchestration
  - skill execution
  - agent delegation
  - teammate orchestration

The point is not to isolate them completely, but to keep ownership obvious.

## Layer 1: App or host

Your product owns user experience, approvals, local commands, and app-specific presentation.
It does not need to re-implement the runtime loop.

## Layer 2: Assembly

`RuntimeConfig` describes the desired runtime posture.
`RuntimeAssembly` exposes the assembled surface for prompts, sessions, binding, and inspection.

This is also where package and distribution posture becomes visible:

- `weavert-core`
- `weavert-default`
- `weavert-full`
- explicit package manifests and requested packages

## Layer 3: Session

Sessions normalize ingress, maintain transcript continuity, and decide whether input should admit a turn.
They are the boundary between "something happened" and "a turn should execute".

## Layer 4: Turn engine

The turn engine owns one cycle of execution:

- model request and response handling
- tool orchestration
- skill execution
- agent delegation
- terminal result production

## Layer 5: Cross-cutting runtime services

Hooks, permissions, elicitation, memory, compaction, and host bridges shape execution from the side without replacing the turn engine itself.

## Principles that show up everywhere

Keep these rules in mind while reading the deeper architecture pages:

- ingress before turn execution
- prompt-visible context separate from runtime-private state
- transcript truth separate from active context projection
- attempt-final separate from turn-final
- lifecycle ownership stays explicit

## What most integrators should not do first

Do not treat `TurnEngine` as the ordinary SDK entrypoint.
Most users should stay at the `RuntimeConfig`, `RuntimeAssembly`, local definitions, package selection, and bound-host levels.

## Next step

- Read `request-lifecycle.md` to trace one input through ingress, turn execution, and terminal persistence.
- Read `package-system.md` if your architecture question is really about package ownership or activation.
- Use `persistence-and-state.md` when the boundary question is specifically about durable artifacts.

## See also

- `request-lifecycle.md`
- `package-system.md`
- `persistence-and-state.md`
- `../deep-dives/current-system-architecture.md`
