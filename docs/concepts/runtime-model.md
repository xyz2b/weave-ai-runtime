# Runtime Model

The most useful mental model for WeaveRT is a layered runtime, not a single assistant object.

```text
Your App / Host
  -> RuntimeConfig
  -> RuntimeAssembly
  -> SessionController
  -> TurnEngine
  -> Tools / Skills / Agents / Memory / Hooks / Permissions
```

## Who is this for?

- Adopters who already know the landing-page story and now need the core runtime vocabulary.

## Prerequisites

- Read `../introduction/what-is-weavert.md` first.
- Skim `../getting-started/quickstart.md` if you want the terminology anchored in a runnable path.

## The four user-facing runtime surfaces

Most adopters should think in terms of four stable entrypoints:

- `RuntimeConfig`
  - declares how the runtime should be assembled
- `RuntimeAssembly`
  - exposes one-shot helpers, sessions, binding, and inspection
- `BoundHostRuntime`
  - adds host-owned lifecycle and grouped bound surfaces
- `DefinitionSourcePaths`
  - controls how local tools, agents, and skills are discovered

## Core objects

### `RuntimeConfig`

Declares assembly posture such as:

- working directory and discovery sources
- distribution and package choices
- model client and routes
- stores and memory configuration
- host-related integration settings

### `RuntimeAssembly`

The assembled runtime surface.
It exposes helper entrypoints, session creation, host binding, inspection, and invocation visibility.

### Session

A session owns transcript continuity and ingress handling.
Inputs are normalized before a turn is admitted.

### Turn engine

A turn owns one execution cycle: model invocation, tool orchestration, skill execution, agent delegation, and terminal result production.

## Five architecture rules worth remembering

### 1. Ingress happens before turn execution

Inputs do not jump straight into the turn engine.
Session ingress first decides what should become transcript-visible history, what should stay private, and whether a turn should run at all.

### 2. Prompt-visible context is not the same thing as runtime-private state

Model-visible context should contain the parts of memory, hooks, attachments, or session hints that are safe for the model.
Runtime-private state should keep permissions, diagnostics, route metadata, and execution-policy state out of the prompt.

### 3. Transcript truth is not the same thing as the active context view

The durable transcript is the historical record.
The active context is the runtime-built projection for one turn.
Keeping them separate allows context projection, compaction, and recovery without rewriting history.

### 4. Attempt-final and turn-final are different moments

One model attempt can finish without the entire turn being complete.
This distinction is what lets tool continuation, recovery policy, and richer terminal metadata work cleanly.

### 5. Ownership should stay obvious

- the host owns product UX and approvals
- the session owns continuity
- the turn engine owns one execution cycle
- tools, skills, and delegated agents own their own execution scope

## Helper ownership semantics

When you use the helper surfaces, session ownership matters:

- `run_prompt()` and `stream_prompt()` own the session lifecycle for that call
- `run_prompt_report()` and `stream_prompt_report()` also own the session lifecycle and complete the report surface
- `run_prompt_report_in_session()` and `stream_prompt_report_in_session()` only wrap the current turn inside a caller-owned session

This is why a report helper is often the best default for headless validation, but a bound host or explicit session is better for longer-lived shells and apps.

## What ordinary users should extend

Start by extending the runtime through:

- `.weavert/tools/*.py`
- `.weavert/agents/*.md`
- `.weavert/skills/**/SKILL.md`
- `RuntimeConfig` presets and package selection

Ordinary users should not start by changing turn orchestration internals.

## Next step

- Read `tools-agents-skills.md` to understand the ordinary extension seams.
- Read `hosts-permissions-memory.md` when you need the control-plane and state boundaries.
- Move to `../architecture/overview.md` for the implementation-oriented layer map.

## See also

- `tools-agents-skills.md`
- `hosts-permissions-memory.md`
- `../architecture/overview.md`
- `../reference/runtime-config.md`
