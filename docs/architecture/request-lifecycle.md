# Request Lifecycle

This page answers one question: how does one prompt move through the runtime?

```text
User or Host input
  -> session ingress normalization
  -> session decides whether to admit a turn
  -> active context assembly
  -> model invocation
  -> tools / skills / agents run as needed
  -> recovery or continuation if needed
  -> terminal turn result
  -> transcript and durable artifacts update
```

## Who is this for?

- Readers evaluating how the runtime is assembled, executed, and persisted under the hood.

## Prerequisites

- Read `../concepts/runtime-model.md` first.
- Use the relevant concept pages as vocabulary support before treating this as the deeper architecture layer.

## Step 1: Ingress normalization

Session ingress handles new input before the turn engine sees it.
It separates concerns such as:

- normalized messages
- replay outputs
- prompt updates
- private updates

This keeps the session, not the turn engine, as the authority for what should actually become turn input.

## Step 2: Turn admission

Not every input becomes a new model turn.
The session decides whether the input:

- updates transcript-visible history
- only replays host-facing output
- updates private context
- or truly admits a turn

## Step 3: Active context assembly

Before model invocation, the runtime builds the active context for this turn.
That view may include:

- selected memory fragments
- hook-provided context
- compaction results
- session hints and attachments

This projected context is not identical to the whole durable transcript.

## Step 4: Model and execution loop

The turn engine drives model calls, tool use, skill execution, and agent delegation until the turn reaches a terminal outcome.

This is also where the runtime coordinates local continuation for tool results rather than handing that authority entirely to the provider.

## Step 5: Control-plane shaping

Permissions, hooks, memory, and host interactions can influence the turn without taking over its ownership.
For example:

- a tool call may be denied or rewritten
- host mediation may be required
- recovery policy may classify a route failure

## Step 6: Attempt-final versus turn-final

One model attempt can finish without the whole turn being done.
This distinction is what makes:

- tool continuation
- stop handling
- richer terminal metadata
- recovery decisions

easier to reason about.

## Step 7: Terminal result and persistence

Once the turn is truly terminal, the runtime updates the transcript and any configured durable artifacts such as child-run state, task or job state, and memory effects.
The host can then render or react to the result.

## Why the boundary matters

This separation helps you diagnose whether a problem came from:

- ingress handling
- context projection
- provider behavior
- tool execution
- host mediation
- persistence or recovery

## Next step

- Read `persistence-and-state.md` if you need the authoritative owner for the artifacts created at turn end.
- Use `../guides/register-hooks.md` when you want to affect one of the lifecycle phases described here.
- Move to `../reference/workflow-observability.md` when you need the stable observability projection of these steps.

## See also

- `overview.md`
- `persistence-and-state.md`
- `../deep-dives/current-system-architecture.md`
