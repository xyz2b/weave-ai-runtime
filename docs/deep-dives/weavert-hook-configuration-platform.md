# WeaveRT Hook Configuration Platform

> Documentation note: This file remains the deep-dive reference for the hook registration model. Start with `docs/guides/register-hooks.md`; use `docs/reference/hook-registration.md` for the compact lookup page and `docs/guides/extend-the-control-plane.md` for the wider control-plane boundary.

This reference keeps the low-level hook-platform contract: phases, registration objects, scope semantics, diagnostics, and policy limits.

Primary docs path:

- Hook authoring -> `docs/guides/register-hooks.md`
- Hook quick reference -> `docs/reference/hook-registration.md`
- Control-plane overview -> `docs/guides/extend-the-control-plane.md`

Use this page when you already know how to register a normal hook and now need the underlying platform model.

## 1. What the platform is

The hook platform is the session-scoped `HookBus` contract inside the runtime loop.
It gives the runtime one place to normalize, schedule, match, execute, merge, block, and diagnose hook behavior.

Use it when you need to:

- intercept tool execution
- shape request context or model routing
- attach approval or recovery logic
- emit audit or lifecycle observations
- carry reusable hook behavior through runtime, host, session, or skill surfaces

This is not the same as the pre-request context-contributor system.
Use HookBus for event phases.
Use context contributors for pre-request assembly contributions.

## 2. Public phase model

The current public phases fall into three buckets:

| Bucket | Phases | Portability posture |
| --- | --- | --- |
| stable public | `SessionStart`, `SessionEnd`, `PreToolUse`, `PostToolUse`, `PostToolUseFailure`, `PreModelRequest`, `PostModelResponse`, `Stop`, `Notification`, `Elicitation`, `ElicitationResult` | ordinary v1 surface |
| advanced public | `UserPromptSubmit`, `SubagentStop`, `PreCompact`, `PostCompact`, `PreContextAssemble`, `PostContextAssemble`, `RecoveryDecision` | available, but not the default portability promise |
| internal-only | everything else | implementation detail; rejected by public registration |

Default recommendation:

- stay on stable public phases first
- move to advanced phases only when the stable set is genuinely insufficient

## 3. Registration model

At the canonical level, one registration is a `HookRegistrationRequest`.
The fields that matter most are:

| Part | Meaning |
| --- | --- |
| `phase` | which lifecycle point the hook attaches to |
| `match` | which payloads or targets it applies to |
| `scope` | how long the hook lives |
| `handler` | what logic runs when matched |
| `contract` | which effect fields are expected to be consumable |
| `once` / `metadata` | one-shot behavior and attached metadata |

Important scope values:

| Scope | Good fit |
| --- | --- |
| `session-template` | host- or runtime-level template hooks that materialize into sessions later |
| `session` | hooks that remain active for a session lifecycle |
| `turn` | one-turn behavior; part of the advanced surface |

Handler kinds:

| Handler kind | Status |
| --- | --- |
| `callback` | stable public default |
| `http` | advanced or package-specific |
| `command` | advanced or package-specific |
| `agent` | advanced or package-specific |
| `prompt` | advanced or package-specific |

Effect contract rule:

- unsupported effect fields are ignored rather than silently treated as successful
- those ignored fields should appear in diagnostics

## 4. Authoring layers

The public registration surface is easiest to reason about in three layers:

| Layer | Good fit |
| --- | --- |
| simple registrars such as `runtime.hooks`, `bound.hooks`, `session.hooks` | normal callback-first hook authoring |
| `.typed` | explicit effect intent without raw object authoring |
| `.raw` | direct `HookRegistrationRequest` control |

Selection guidance:

- start with the simple surface
- switch to `.typed` when you want explicit effect declaration
- switch to `.raw` only when you need exact low-level control over scope, contract, or handler manifest

If you receive a handle after registration:

- `activation_state` tells you whether it is pending, active, released, expired, or rejected
- `release()` is idempotent

## 5. Registration sources

Multiple source surfaces converge on the same platform model:

| Registration source | Typical entrypoint | Default scope | Good fit | Status |
| --- | --- | --- | --- | --- |
| runtime config | `RuntimeConfig(hooks=...)` | `session-template` | default capability that every session should inherit | stable public |
| host API | `bound.hooks...` | `session-template` | host-owned policy, routing, or audit | stable public |
| session API | `session.hooks...` | `session` | dynamic behavior for one session | stable public |
| turn API | `session.hooks.advanced.turn...` | `turn` | one-turn or short-lived behavior | advanced |
| skill hooks | skill frontmatter `hooks` | usually `session` or `turn` | workflow-packaged behavior | stable public |
| legacy definitions | older phase-grouped structures | compatibility-dependent | migration path only | compatibility-only |

Important boundary notes:

- `bound.hooks...` first mounts at the template layer; it does not instantly inject one live hook into every existing session
- skill hooks remain the mature definition-level hook path
- agent-owned hooks are not the ordinary v1 path and are rejected by default assembly

## 6. Matching, diagnostics, and debugging

After registration, use inspection and dispatch traces rather than guessing from the callback alone.

Primary inspection surfaces:

- `list_hooks(...)`
  - confirms phase, scope, owner, source, and activation state
- `list_hook_dispatch_traces(...)`
  - confirms whether a dispatch matched, blocked, ignored, or applied a registration

In dispatch traces, the most useful fields are usually:

- `matched_registrations`
- `blocked_registrations`
- `ignored_effects`
- `winner_summary`
- `applied_outcome`

If an effect field is unsupported for that phase, it should appear under `ignored_effects`.
If policy blocks an external handler, it should appear under `blocked_registrations`.

## 7. Recovery and policy boundaries

Two platform-level boundaries matter most:

### 7.1 Stop / recovery is formal control flow

`Stop` is not just a logging event.
It can halt continuation and preserve recoverable state.
`RecoveryDecision` is the formal continuation path when the runtime later resumes.

This is the right place for:

- approval gating
- continue-after-failure flows
- manual recovery decisions
- stop-and-resume control paths

### 7.2 External handlers are restricted by default

The manifest model still supports external handler kinds, but:

- `callback` is the only stable public default
- `http`, `command`, `agent`, and `prompt` are not the ordinary safe default
- external handlers require explicit handler policy allowance

Do not assume an external handler kind is active just because a registration document mentions it.

## 8. What to use for a first integration

For normal adoption:

1. start with `session.hooks` on a stable phase
2. confirm registration with `list_hooks(...)`
3. confirm dispatch with `list_hook_dispatch_traces(...)`
4. only move to typed, raw, advanced, or external-handler paths when the simple surface stops being enough

Use these documents for that path:

- first working example -> `docs/guides/register-hooks.md`
- compact lookup -> `docs/reference/hook-registration.md`
- wider host / permission context -> `docs/guides/extend-the-control-plane.md`

## 9. Related docs

- `docs/guides/register-hooks.md`
- `docs/reference/hook-registration.md`
- `docs/guides/extend-the-control-plane.md`
- `docs/deep-dives/weavert-control-plane-extension-guide.md`
- `docs/deep-dives/current-system-architecture.md`
