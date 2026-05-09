# WeaveRT Tool, Agent, and Skill Authoring

> Documentation note: This file remains the deep-dive reference for definition authoring contracts. Start with `docs/concepts/tools-agents-skills.md`, then use `docs/guides/add-a-tool.md`, `docs/guides/add-an-agent.md`, and `docs/guides/add-a-skill.md` for the ordinary authoring path.

This reference keeps the contract-level boundary ledger for local definition authoring: discovery, precedence, stable fields, execution boundaries, and compatibility notes.

Primary docs path:

- Tools / agents / skills concepts -> `docs/concepts/tools-agents-skills.md`
- First real project path -> `docs/guides/build-your-first-project.md`
- Add a tool -> `docs/guides/add-a-tool.md`
- Add an agent -> `docs/guides/add-an-agent.md`
- Add a skill -> `docs/guides/add-a-skill.md`

Use this page when you need to answer questions such as:

- how `DefinitionSourcePaths` discovery and precedence really work
- which fields are stable runtime contract versus merely parsed
- how file-backed tools are validated
- how skill hooks differ from agent hooks
- which transport constraints matter on the bundled OpenAI route

## 1. Core posture

The runtime closes over the main loop, session ingress, turn state machine, recovery, memory, and host bridge.
Ordinary user extensions should enter through definitions and public control-plane seams, not by rewriting the runtime loop.

The main local definition types are:

- tool
  - executable capability with schema, traits, and permissions
- agent
  - named role with prompt posture and execution policy
- skill
  - reusable workflow step that runs inline or in a child agent

## 2. Discovery and precedence

The recommended local layout is:

```text
your-project/
└── .weavert/
    ├── tools/
    ├── agents/
    └── skills/
```

Default discovery rules:

| Definition type | File-backed path |
| --- | --- |
| tool | `tools/*.py` |
| agent | `agents/*.md` |
| skill | `skills/**/SKILL.md` |

For ordinary workflow assembly, the default source roots are:

- `~/.weavert`
- `<project>/.weavert`

Registry precedence is:

```text
bundled > user > project
```

Implications:

- a same-name bundled definition wins over user and project definitions
- a same-name user definition wins over project definitions
- project-local files are not a silent built-in override mechanism

Recommended practice:

1. Prefer new names for local definitions.
2. Use Python assembly and `BuiltinPackConfig` only when you truly need to replace a bundled surface.
3. Do not assume `.weavert/` naming alone can override first-party behavior.

## 3. Tool authoring contract

### 3.1 Supported file-backed form

For executable local tools, the supported file-backed path is a Python module that resolves to a concrete `ToolDefinition`.
The module must export one of:

- `TOOL_DEFINITION`
- `TOOL`
- `build_tool_definition()`

Unsupported forms include:

- `.weavert/tools/*.json`
- `.weavert/tools/*.yaml`
- `.weavert/tools/*.yml`
- mapping-style exports in place of a `ToolDefinition`
- file-backed tools without `execute`

### 3.2 Stable `ToolDefinition` fields

| Field | Current role |
| --- | --- |
| `name` | canonical tool name; required |
| `description` | capability description; required |
| `input_schema` | runtime input contract and provider exposure shape |
| `output_schema` | optional formal result contract |
| `aliases` | optional alternate names |
| `search_hint` | optional search/discovery hint |
| `traits` | static posture such as read-only, concurrency, destructive |
| `semantics` | advanced dynamic execution semantics |
| `validate_input` | optional tool-local validation |
| `check_permissions` | optional tool-level permission gate |
| `execute` | executable entrypoint; required for runnable tools |

The most commonly used traits are:

- `read_only`
- `concurrency_safe`
- `destructive`
- `interrupt_behavior`

Practical rule of thumb:

- read-only query tools should usually declare `read_only=True` and `concurrency_safe=True`
- mutation or side-effecting tools should describe that posture honestly rather than inheriting a read-only surface by accident

### 3.3 Public execution boundary for non-bundled tools

Non-bundled user tools run on the public execution path, not the internal privileged path.
They should not assume direct access to the runtime's private service bag.

Publicly useful context typically includes:

- session, turn, and agent metadata
- working directory and current messages
- tool, agent, and skill catalogs
- permission context
- session, turn, and file state
- memory access
- refresh handles
- a read-only `private_context_view`

But user tools should not assume direct access to:

- internal runtime services
- raw tool pool internals
- mutable private context internals

Declaring a privileged-sounding execution class in a user definition does not upgrade the tool into a privileged runtime path.

### 3.4 Schema guidance for the bundled OpenAI route

The bundled `openai_default` route exports `input_schema` into strict Responses function tools.
The runtime contract stays the same, but some schema styles are safer on that route.

Recommended posture:

- use a top-level object schema
- declare fields explicitly
- prefer `additionalProperties: false`
- provide a complete `items` schema for arrays
- treat the runtime schema as canonical; do not encode provider quirks directly into the tool contract

Current important limitation:

- schema-valued `additionalProperties` is not supported on the bundled adapter and causes `tool_schema_error`

If you need the fine-grained adapter behavior, see `docs/deep-dives/weavert-openai-responses-adapter.md`.

## 4. Agent authoring contract

### 4.1 File structure

Agents are Markdown files under `agents/*.md`.
The runtime reads:

- frontmatter
- prompt body

### 4.2 Stable runtime-facing fields

| Field | Current role |
| --- | --- |
| `name` | required agent name |
| `description` | required agent description |
| `tools` | allowed tool pool |
| `disallowedTools` | explicitly blocked tools |
| `skills` | allowed skill pool |
| `model` | default model name |
| `modelRoute` | default route |
| `effort` | reasoning-effort hint |
| `permissionMode` | permission posture |
| `maxTurns` | default max internal turn budget |
| `background` | default background execution preference |
| `memory` | memory scope |
| `isolation` | isolation mode |

`maxTurns` is a static ceiling.
If a runtime invocation also passes `max_turns`, the effective budget is the smaller of the two values.
If neither side sets a value, the runtime currently falls back to `8`.

### 4.3 Stable authoring guidance

Good agent definitions usually:

- keep the tool list narrower than "everything"
- define one role clearly
- push execution details into tools rather than prompt prose
- use memory and isolation settings intentionally instead of inheriting defaults blindly

### 4.4 Parsed but not yet mature fields

These fields are parsed, but should not be treated as stable authoring contract yet:

- `hooks`
- `initialPrompt`
- `criticalSystemReminder_EXPERIMENTAL`
- `mcpServers`

Important boundary:

- agent-owned hooks are not the ordinary recommended v1 path
- default assembly rejects agent-owned hooks
- only explicit legacy compatibility modes continue to tolerate them

If you need definition-level hooks today, prefer skill hooks.

## 5. Skill authoring contract

### 5.1 File structure

Skills live at `skills/<slug>/SKILL.md`.
The runtime uses:

- frontmatter
- Markdown body

By default, the folder slug is the skill name.

### 5.2 Stable runtime-facing fields

| Field | Current role |
| --- | --- |
| `description` | required or inferred summary |
| `context` | `inline` or `fork` |
| `agent` | target agent for fork mode |
| `allowed-tools` | narrows the tool pool |
| `model` | skill-level model override |
| `effort` | skill-level effort override |
| `paths` | path activation scope |
| `user-invocable` | whether a user may invoke it explicitly |
| `disable-model-invocation` | whether the model may invoke it |
| `argument-hint` | invocation hint text |
| `arguments` | argument names |
| `hooks` | skill hook definitions |
| `shell` | default shell for shell blocks |

### 5.3 `inline` versus `fork`

Use `inline` when the skill should:

- inject prompt or workflow guidance into the current turn
- narrow policy without creating a child run
- stay close to the caller's current context

Use `fork` when the skill should:

- create a child-agent run
- carry its own execution boundary
- leave behind a separate child-run record

### 5.4 Skill hooks are the mature definition-level hook path

Current boundary:

- skill hooks have real runtime semantics
- skill hooks work in both inline and fork paths
- inline skill hooks register against the current session or turn and release with that lifecycle
- fork skill hooks can travel with child execution

By contrast:

- agent hooks are not the ordinary supported authoring path

### 5.5 Shell expansion boundary

Shell expansion is supported with clear limits:

- only local file-backed skills can use it
- bundled skills should not depend on it
- the required shell tool must actually be available
- execution fails closed rather than silently skipping

Two supported shell-block forms remain:

- inline `!`
- fenced shell blocks such as `bash`

### 5.6 Path activation is runtime semantics

`paths` is not just a UI filter.
It participates in runtime invocation resolution and affects:

- whether the skill is visible
- whether a user may invoke it
- whether the model may invoke it

The runtime may also discover deeper `.weavert/skills/` roots as session path context expands.
Skill authoring should therefore treat path scope as runtime behavior, not a documentation hint.

## 6. Validation checklist

After adding a definition, validate three things:

1. Discovery
   - the definition was loaded without validation failure or collision surprise
2. Visibility
   - the current session can actually see the invocation you expect
3. Executability
   - the definition is not merely registered; it has the behavior and execution entrypoint you intended

Useful inspection surfaces include:

- `weavert.resolve_invocations(...)`
- `weavert.visible_invocations(session)`
- `weavert.invocation_diagnostics(session)`

For tools specifically:

- discovery alone is not enough
- confirm that the final resolved definition still carries a runnable `execute`

## 7. Related documents

- `docs/deep-dives/weavert-integration-guide.md`
- `docs/deep-dives/weavert-control-plane-extension-guide.md`
- `docs/deep-dives/current-system-architecture.md`
- `docs/deep-dives/weavert-openai-responses-adapter.md`
