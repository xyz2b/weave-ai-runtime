# WeaveRT User Extension Guide

> Documentation note: This file remains a deep-dive reference. Start with `docs/concepts/tools-agents-skills.md`, then use `docs/guides/add-a-tool.md`, `docs/guides/add-an-agent.md`, and `docs/guides/add-a-skill.md` for the ordinary authoring path.

This reference keeps the extension decision ledger: which layer to extend, which replacement seams are real, which infrastructure surfaces are deeper than ordinary authoring, and which contracts should be treated carefully.

Primary docs path:

- Tools / agents / skills boundary -> `docs/concepts/tools-agents-skills.md`
- First real project path -> `docs/guides/build-your-first-project.md`
- Add a tool -> `docs/guides/add-a-tool.md`
- Add an agent -> `docs/guides/add-an-agent.md`
- Add a skill -> `docs/guides/add-a-skill.md`
- Control plane -> `docs/guides/extend-the-control-plane.md`

Use this page when you need to decide whether a change belongs in definitions, packages, the control plane, or deeper infrastructure.

For ordinary users, the primary validation path is still `examples/README.md`.
If you are curating repo-level evidence, the maintainer-facing validation index lives at `docs/maintainers/validation-findings.md`; the more detailed user-centric validation layer and demo findings ledger remain in `docs/maintainers/demo-validation-findings.md`.

## 1. First separate the extension layers

### 1.1 Definition authoring

This is the ordinary user path:

- `tool`
- `agent`
- `skill`

Use it when you are adding or shaping workspace-local capabilities.

### 1.2 Package and control-plane extension

This is the path for reusable runtime behavior that crosses one local definition:

- `RuntimePackageManifest`
- `PackageContribution`
- `HostRuntime`
- stable public hooks
- context contributors
- model routes
- `tool_refresh_callback`

Use it when the change belongs to product integration, reusable capability groups, or lifecycle control.

### 1.3 Infrastructure and persistence

This is the deeper platform path:

- `TranscriptStore`
- `ChildRunStore`
- `MemoryConfig`
- `MemoryProvider`
- `teammate_orchestration`

Use it when you are changing durability, background memory behavior, or long-lived orchestration posture rather than just adding capabilities.

## 2. Extension decision map

| Goal | Preferred seam |
| --- | --- |
| add a new ability | tool, agent, or skill |
| narrow an agent's usable surface | agent fields such as `tools`, `disallowedTools`, `skills`, `memory`, `isolation` |
| restrict where a skill is visible | skill `paths` |
| add approvals or interactive questions | host, permissions, elicitation |
| intercept a lifecycle point | HookBus |
| shape request context before the model call | context contributors |
| refresh the visible tool pool dynamically | `tool_refresh_callback` |
| package multiple surfaces together | runtime package manifest plus contribution |
| persist transcript history | `TranscriptStore` |
| persist child runs | `ChildRunStore` |
| tune memory behavior declaratively | `MemoryConfig` |
| replace the memory backend | `MemoryProvider` plus runtime memory service replacement |
| run durable collaborative orchestration | `teammate_orchestration` |

## 3. Package-owned versus definition-owned extension

Use workspace-local definitions when:

- one capability is local to a project
- you do not need manifest admission or dependency ordering
- the change is still understandable as one tool, agent, or skill

Use packages when:

- one feature owns multiple runtime surfaces
- you need manifest-backed activation
- you need capability lookup, context contributors, or host facets
- you are composing a scenario profile or shared capability family

Important rule:

- same-name project definitions do not override bundled built-ins
- built-in replacement belongs to `BuiltinPackConfig`, not to filename collision

## 4. Infrastructure and persistence boundaries

### 4.1 TranscriptStore

`TranscriptStore` is the formal session-transcript persistence protocol.
Use it when the question is:

- should transcript history be durable?
- where should session truth live?
- how should recovery or audit read past sessions?

Use `RuntimeConfig.transcript_store` rather than inferring durability from one default class name.

### 4.2 ChildRunStore

`ChildRunStore` owns durable child-run truth such as:

- run identity
- parent linkage
- status
- final-state metadata

It is the right seam when you need durable delegated-run history.
It is not the seam that decides wake-up or continuation policy.

### 4.3 MemoryConfig

`MemoryConfig` is the declarative tuning surface for:

- retrieval posture
- extraction posture
- session-memory refresh thresholds
- consolidation cadence

Use config first when you want memory behavior changes without replacing the subsystem.

### 4.4 MemoryProvider and runtime memory service

If you truly need a different backend, the deeper seams are:

- `MemoryProvider`
- runtime-owned memory service replacement

Important current limitation:

- there is no direct `RuntimeConfig.memory_provider` slot today

So replacing memory is deeper than ordinary config tuning.

### 4.5 teammate_orchestration

Use `teammate_orchestration` when you need durable collaborative or background agent behavior with retry, mailbox, and lease semantics.
Do not reach for it when a normal child run or skill fork is enough.

## 5. Things users should not depend on too heavily today

The following are parsed or present, but should not be treated as strong stable extension commitments:

- agent-owned hooks
- agent frontmatter `initialPrompt`
- agent frontmatter `criticalSystemReminder_EXPERIMENTAL`
- agent frontmatter `mcpServers`
- privileged-sounding execution class flags on user-defined tools

Two subtler contract notes:

- `ToolDefinition.output_schema`
  - treat it as a result contract when typed consumers depend on it
  - do not confuse it with the main execution-scheduling contract
- `ToolDefinition.search_hint`
  - treat it as suggestive metadata, not an authoritative runtime seam

If you want the most stable access path, prioritize:

- tool: `input_schema`, `validate_input`, `check_permissions`, `execute`
- agent: `tools`, `disallowedTools`, `skills`, `permissionMode`, `memory`, `isolation`, `modelRoute`
- skill: `context`, `allowed-tools`, `hooks`, `paths`

## 6. User-centric validation and examples

Use the repository-owned guides and demos instead:

- `docs/guides/add-a-tool.md`
- `docs/guides/add-an-agent.md`
- `docs/guides/add-a-skill.md`
- `docs/guides/bind-a-host.md`
- `docs/guides/testing-and-observability.md`
- `examples/README.md`

For the user-centric validation layer and demo findings ledger, use:

- `docs/maintainers/demo-validation-findings.md`

That maintainer ledger is mainly for repo-level evidence curation.
Most users should stay on the public guides and `examples/README.md`.

Keep this file for boundary questions and extension-path selection, not for tutorial walkthroughs.

## 7. Recommended practices

1. Start with tools, agents, and skills before touching deeper runtime seams.
2. Use `bind_host()` when product interaction is required; do not rewrite the session or turn loop first.
3. Prefer hooks or context contributors over turn-engine edits when inserting business control logic.
4. Use `BuiltinPackConfig` for built-in replacement; do not rely on same-name collisions.
5. Use config tuning before replacing persistence or memory backends outright.

## 8. Related documents

- `docs/deep-dives/weavert-definition-authoring-guide.md`
- `docs/deep-dives/weavert-integration-guide.md`
- `docs/deep-dives/weavert-control-plane-extension-guide.md`
- `docs/deep-dives/weavert-hook-configuration-platform.md`
- `docs/deep-dives/weavert-scenario-runtime-pack-architecture.md`
- `docs/deep-dives/current-system-architecture.md`
