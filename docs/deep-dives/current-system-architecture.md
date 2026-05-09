# WeaveRT System Architecture

> Documentation note: This file remains a deep-dive reference for system architecture. Start with `docs/architecture/overview.md` and `docs/architecture/request-lifecycle.md` for the normal reading path.

This reference keeps the architecture-level boundary ledger: system position, ownership rules, request flow, capability layers, state authority, and extension seams.

Primary docs path:

- Architecture overview -> `docs/architecture/overview.md`
- Request lifecycle -> `docs/architecture/request-lifecycle.md`
- Package system -> `docs/architecture/package-system.md`
- Persistence and state -> `docs/architecture/persistence-and-state.md`

Use this page when you need the deeper "why is the boundary drawn here?" answer rather than a walkthrough.

## 1. Purpose

This document answers five architecture questions:

- what the runtime is responsible for
- which layer owns each major concern
- how one request moves across session and turn boundaries
- how tools, skills, agents, memory, and control-plane surfaces fit together
- where extension is expected versus where kernel edits begin

## 2. System position

WeaveRT sits between an app or host and the model-and-capability execution loop.
It is not just a prompt template, and it is not merely a tool catalog.

```text
your app / host
  -> runtime assembly
  -> session ingress and transcript authority
  -> single-turn execution engine
  -> tools / skills / agents / memory / hooks / permissions / host mediation
```

The app owns user experience and deployment choices.
The runtime owns workflow execution semantics.

## 3. Core architecture principles

These principles explain most of the boundaries elsewhere in the system:

### 3.1 Ingress before turn execution

Every input should pass through session ingress before the turn engine sees it.

Why:

- not every input becomes a new model turn
- replay, acknowledgements, and private updates may be session-visible but not turn-admitting
- transcript continuity needs one authority

### 3.2 Prompt-visible context stays separate from runtime-private context

The runtime must distinguish:

- prompt-visible context
- runtime-private state
- diagnostics or control-plane state

Why:

- model-visible context has different safety and correctness requirements
- private state may include host or control-plane information that must not become prompt text
- diagnostics should explain behavior without silently becoming model input

### 3.3 Transcript truth stays separate from active context projection

The transcript is the durable record.
The active context for one turn is a runtime projection assembled from multiple inputs.

Why:

- compacted or retrieved context is not the same thing as transcript truth
- prompt construction can change without redefining durable history

### 3.4 Attempt-final is not the same as turn-final

One model attempt may finish while the turn still needs:

- tool continuation
- recovery handling
- stop / resume logic
- child execution follow-up

This distinction prevents the model transport layer from owning final workflow truth.

### 3.5 Lifecycle owners stay explicit

The app, runtime assembly, session, turn engine, host bridge, and capability runtimes should not silently absorb each other's authority.

That is why WeaveRT keeps boundaries explicit even when the implementation could be made more convenient by merging them.

## 4. Layered ownership view

The system is easiest to reason about as five layers:

```text
App / Host
  -> owns UX, deployment, approvals, shell, presentation

Assembly
  -> owns config, distribution, package selection, runtime posture

Session
  -> owns ingress, transcript continuity, turn admission

Turn Engine
  -> owns one execution cycle, continuation, recovery, terminal result

Cross-cutting services
  -> memory, hooks, permissions, elicitation, compaction, host mediation
```

### 4.1 App or host layer

The app or host owns:

- UX and rendering
- local shell or UI behavior
- deployment-specific provider and store choices
- approval and elicitation presentation
- audit sinks and deployment policy

It should not need to reimplement the runtime loop.

### 4.2 Assembly layer

The assembly layer owns:

- `RuntimeConfig`
- distribution choice
- package admission and selection
- discovery sources
- model routes
- store bindings
- host binding inputs

`RuntimeAssembly` is the resulting runtime entrypoint.

### 4.3 Session layer

The session layer owns:

- ingress normalization
- transcript continuity
- private updates and replay handling
- deciding whether input truly admits a new turn

This is the boundary between "something happened" and "a turn should execute."

### 4.4 Turn-execution layer

The turn engine owns:

- active context assembly
- model request / response processing
- tool orchestration
- skill execution
- agent delegation
- recovery and continuation
- terminal turn result production

This is the runtime's main execution core.

### 4.5 Cross-cutting control-plane layer

The control plane shapes execution from the side without taking over turn ownership.
It includes:

- hooks
- permissions
- elicitation
- memory
- compaction
- host bridge mediation
- job and task-facing services

## 5. Request flow ledger

The runtime-owned flow is:

```text
input
  -> ingress normalization
  -> turn-admission decision
  -> active context assembly
  -> model attempt
  -> tools / skills / agents as needed
  -> continuation or recovery
  -> turn-final result
  -> transcript and durable artifact updates
```

Important consequences:

- a host event may affect the session without becoming a new turn
- active context is a projected view, not the whole transcript or private state bag
- tool continuation is runtime-owned even if the provider supports tool calls
- recovery belongs to the runtime control plane, not to a single model transport

## 6. Execution-capability layers

WeaveRT keeps three capability layers separate on purpose:

### 6.1 Tool runtime

Tools own executable capability with structured input and output contracts.
They are best for:

- file or workspace operations
- API or service calls
- reusable structured capability

### 6.2 Skill runtime

Skills own reusable workflow steps.
They are best for:

- inline workflow guidance
- reusable review or verification procedures
- delegated forked subflows

### 6.3 Agent runtime

Agents own role and execution posture.
They are best for:

- named workers such as reviewer or planner
- constrained delegated roles
- prompt identity plus policy choices

Keeping these layers separate prevents prompts from absorbing too much execution logic and keeps reusable workflow pieces composable.

## 7. Invocation visibility and capability resolution

Capability resolution is session-aware rather than just repo-wide static discovery.
Visibility may depend on:

- discovered definitions
- package contributions
- path activation
- host or policy narrowing
- request-time capability refresh

This is why "file exists on disk" is not enough to answer whether a capability is actually available in a session.

## 8. Memory runtime boundary

Memory is a cross-cutting runtime service, not one agent's private trick.

The important architecture rules are:

- memory policy is runtime-owned
- retrieval and extraction posture should remain configurable
- memory selection for a turn is part of active context assembly
- memory does not replace transcript truth
- compaction remains related but distinct

Use `layered-memory-weavert-v2.md` when the question is specifically about the layered memory model.

## 9. Host bridge and interactive control plane

The host bridge is the formal seam for:

- permissions
- elicitation
- notifications
- turn events
- host-owned lifecycle presentation

The host may render or mediate those interactions, but the runtime still owns when those interactions are required and how they affect workflow control flow.

## 10. Team and delegated orchestration

Delegation and team-style orchestration remain runtime-owned workflow semantics.

The host may:

- observe events
- render progress
- provide a UX for collaboration

But the host should not become the hidden authority for:

- team state
- delegation semantics
- child-run control flow

## 11. State and persistence authority

The runtime produces several kinds of durable artifacts, but not every artifact has the same owner.

Useful mental split:

| Artifact family | Primary authority |
| --- | --- |
| transcript history | session / transcript store |
| active-turn control flow | turn engine |
| memory state | memory service and memory policy |
| child-run or delegated execution records | runtime services and configured stores |
| host presentation state | host |

The key rule is that prompt assembly views and host rendering views must not silently redefine authoritative persisted state.

## 12. Extension seams

The main supported extension seams are:

- local tools, agents, and skills
- package manifests and package contributions
- model routes
- memory policy
- stable public hooks
- host binding
- request-time context contributors

These are usually the right first move before editing kernel-owned session or turn internals.

## 13. What most integrators should not touch first

Most adopters should not begin by editing:

- `SessionController`
- `TurnEngine`
- core runtime-private state handling
- kernel-owned first-party assembly tables

That is maintainership-level work, not ordinary integration.

## 14. Related docs

- `docs/architecture/overview.md`
- `docs/architecture/request-lifecycle.md`
- `docs/architecture/persistence-and-state.md`
- `docs/deep-dives/weavert-integration-guide.md`
- `docs/deep-dives/weavert-control-plane-extension-guide.md`
- `docs/deep-dives/layered-memory-weavert-v2.md`
