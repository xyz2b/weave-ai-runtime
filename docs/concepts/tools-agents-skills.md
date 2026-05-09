# Tools, Agents, and Skills

WeaveRT keeps these extension types separate on purpose.
They solve different problems and should stay distinct if you want the runtime to remain composable.

## Who is this for?

- Adopters who already know the landing-page story and now need the core runtime vocabulary.

## Prerequisites

- Read `../introduction/what-is-weavert.md` first.
- Skim `../getting-started/quickstart.md` if you want the terminology anchored in a runnable path.

## At a glance

| Surface | Owns | Reach for it when | File-backed path |
| --- | --- | --- | --- |
| Tool | execution and structured I/O | you need a reusable capability with schema, traits, and permissions | `.weavert/tools/*.py` |
| Agent | role and prompt posture | you need a named worker such as reviewer, planner, or support agent | `.weavert/agents/*.md` |
| Skill | reusable workflow step | you need a named procedure such as summarize, verify, or review | `.weavert/skills/**/SKILL.md` |

## Discovery surfaces

The runtime discovers local definitions through `DefinitionSourcePaths`.
The default ordinary workflow path includes:

- `~/.weavert`
- `<project>/.weavert`

Default file-backed discovery rules are:

- tools: `tools/*.py`
- agents: `agents/*.md`
- skills: `skills/**/SKILL.md`

## Source precedence matters

Local files are not a magical override system.
The current practical precedence is:

- bundled
- user
- project

That means a project-local file with the same name as a bundled built-in should not be your default override strategy.
Prefer one of these instead:

- give your project-local definition a new name
- use `BuiltinPackConfig` when you truly need to replace a bundled surface in Python assembly code

## Tools

Tools do work.
They are the best fit for:

- file inspection or mutation
- API or service calls
- structured project analysis
- reusable capability shared by many agents or skills

Important authoring rules:

- file-backed tools are Python modules, not JSON or YAML files
- the module should export a concrete `ToolDefinition`
- explicit object schemas are better than open-ended payloads
- traits such as `read_only`, `concurrency_safe`, and `destructive` should match real behavior

## Agents

Agents own role behavior and prompt identity.
They are the best fit for:

- a reusable reviewer or planner
- a worker with a narrower tool pool
- a named delegated role inside a larger workflow

Good agent hygiene:

- keep the tool list narrower than "everything"
- keep the prompt focused on role, output, and decision posture
- let tools perform execution details instead of embedding them in prompt prose

Also note that agent-owned hooks are not the ordinary recommended path.
Prefer skill hooks or runtime/session/host hook registration when you need lifecycle injection.

## Skills

Skills package reusable workflow steps.
They are a good fit for:

- a repeatable summarize / verify / review step
- a small reusable workflow with arguments
- a named operation that should run either inline or in a child agent

A useful first design question is whether the skill should run:

- `inline`
  - when you want to stay inside the current turn context
- `fork`
  - when you want a child agent run with its own delegated execution boundary

## Runtime primitives that are not just one agent's private feature

Some surfaces look workflow-specific but should be treated as framework-level primitives, not private agent tricks.
Two good examples are:

- `task_*`
- `job_*`

If your design depends on shared task lists or job monitoring, think of those as runtime capability surfaces that many agents or hosts may observe, not just a single prompt convention.

## When a package is the better abstraction

If you are no longer adding one local tool, agent, or skill, but instead need:

- a manifest-backed capability group
- dependency ordering
- capability registry lookups
- lifecycle participation

then you are probably crossing from local definition authoring into package composition.
See `packages-and-scenario-packs.md` for that boundary.

## Common mistakes

- putting execution logic in an agent prompt instead of a tool
- using a skill when a simple tool is enough
- expecting project-local names to silently override bundled built-ins
- trying to express package ownership with only more `.weavert/` folders

## Next step

- Start authoring through `../guides/add-a-tool.md`, `../guides/add-an-agent.md`, or `../guides/add-a-skill.md`.
- Move to `packages-and-scenario-packs.md` if your change is growing beyond one local definition.

## See also

- `../guides/add-a-tool.md`
- `../guides/add-an-agent.md`
- `../guides/add-a-skill.md`
- `packages-and-scenario-packs.md`
- `../deep-dives/weavert-definition-authoring-guide.md`
