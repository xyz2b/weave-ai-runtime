# Hosts, Permissions, and Memory

These are control-plane concerns.
They shape how the runtime operates, not just what one agent says.

## Who is this for?

- Adopters who already know the landing-page story and now need the core runtime vocabulary.

## Prerequisites

- Read `../introduction/what-is-weavert.md` first.
- Skim `../getting-started/quickstart.md` if you want the terminology anchored in a runnable path.

## Hosts

A host is the product-facing owner of lifecycle and UX.
Typical hosts are CLI shells, SDK wrappers, web backends, or app shells.

Hosts usually own:

- startup and shutdown
- approvals and elicitation
- notifications and turn-event rendering
- app-specific local commands or presentation

When you bind a host, the preferred bound surfaces are grouped rather than flat:

- `bound.prompts`
- `bound.sessions`
- `bound.hooks`
- `bound.inspection`
- `bound.work`

## Permissions and elicitation

Permissions keep risky actions explicit.
They are especially important for:

- write tools
- shell commands
- network access
- delegated agents or long-running work

The host may participate in approval decisions, but the runtime still owns the control-plane semantics of what is being requested and when.

Elicitation sits nearby: when the runtime needs more human input, the host is often the surface that can ask for it, render context, and pass the answer back.

## Prompt-safe context versus runtime-private state

This boundary is one of the most important design rules in WeaveRT.

- prompt-visible context should contain model-safe memory, attachments, and session hints
- runtime-private state should keep permissions, diagnostics, route metadata, and execution policy out of the prompt

Tools, hosts, and runtime services may still need access to private state even when the model should not.

## Memory is layered, not just one prompt field

WeaveRT separates durable artifacts from prompt-visible context.
The higher-level memory model lives in `memory-model.md`, but the quick summary is:

- long-term memory
  - shared durable memory such as preferences, conventions, and topics
- agent namespace memory
  - durable notes scoped to one agent namespace
- session memory
  - continuity artifacts for one session
- consolidation memory
  - slower background aggregation and merge work

## Why this separation matters

Important distinctions to keep in mind:

- transcript truth is not the same thing as the currently projected prompt context
- runtime-private state should not leak into prompt-visible context
- durable memory, child runs, tasks, and jobs should remain inspectable

## When you should move from a simple project to host binding

Stay on the starter and ordinary workflow path when you only need local tools, agents, or skills.
Move into host binding when you need:

- approval UX
- longer-lived sessions
- turn-event rendering
- app-specific local commands
- product-owned durable state presentation

## Next step

- Move to `../guides/bind-a-host.md` when you need lifecycle, approval, or presentation ownership.
- Use `../guides/extend-the-control-plane.md` for hooks, permissions, elicitation, and tool refresh seams.
- Read `memory-model.md` when the state boundary question is specifically about memory behavior.

## See also

- `memory-model.md`
- `../guides/bind-a-host.md`
- `../guides/extend-the-control-plane.md`
- `../guides/register-hooks.md`
- `../guides/testing-and-observability.md`
- `../architecture/persistence-and-state.md`
- `../reference/memory-configuration.md`
- `../deep-dives/layered-memory-weavert-v2.md`
