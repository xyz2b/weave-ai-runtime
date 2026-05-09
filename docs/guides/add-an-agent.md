# Add an Agent

## Who is this for?

Users who need a named prompt role such as reviewer, planner, or support specialist.

## Prerequisites

- a working project with `.weavert/agents/`
- a clear role that should be reusable across sessions or workflows

## What an agent should own

An agent should own role behavior, prompt identity, and scope posture.
It should not become the place where you hide execution logic that really belongs in tools.

## Steps

1. Create `.weavert/agents/reviewer.md`
2. Give the agent a name, description, and only the tools it actually needs
3. Keep the instruction focused on role, output, and decision posture
4. Call the agent from your project or from another runtime surface

Minimal example:

```md
---
name: reviewer
description: Review a proposed change and return a terse verdict.
tools:
  - check_file
---
You are the reviewer for this workspace.
Inspect the evidence you need, then return a short verdict and one recommendation.
```

## A good agent design checklist

- keep the tool pool smaller than "everything"
- define what success looks like in the prompt
- push structured work into tools and reusable procedures into skills
- use delegation only when a narrower child role helps

## Hook note

Agent-owned hooks are not the ordinary recommended extension path.
If you need lifecycle injection, prefer:

- skill hooks
- runtime or session hook registration
- bound-host hook registration

## Expected result

The runtime discovers the agent by name and can route work to it as a distinct prompt-owned role.

## Next step

Validate the seam with `python3 -B -m examples.agents.file_backed_agent_demo` or `python3 -B -m examples.agents.scoped_agent_delegation_demo`.

## See also

- `../concepts/tools-agents-skills.md`
- `add-a-skill.md`
- `../../examples/agents/workspace/.weavert/agents/release-reviewer.md`
