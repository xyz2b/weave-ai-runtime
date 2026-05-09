# Add a Skill

## Who is this for?

Users who want a reusable workflow step such as summarize, verify, review, or clarify.

## Prerequisites

- a working project with `.weavert/skills/`
- a repeatable workflow step that should be named and reused

## The first design choice: inline or fork

Before you write the skill, decide whether it should run:

- `inline`
  - when it should stay inside the current turn context
- `fork`
  - when it should run as a child agent step with a clearer delegated boundary

## Steps

1. Create `.weavert/skills/release-summary/SKILL.md`
2. Choose `inline` or `fork`
3. Keep the arguments and expected output small and explicit
4. Validate the execution mode you chose before composing a larger workflow

Minimal example:

```md
---
description: Draft a short release summary in a child agent run.
context: fork
agent: skill-writer
---
Draft a release summary for ${ARG1}.
```

## When hooks belong in a skill

Skill hooks are the ordinary recommended authoring path when the extra behavior should travel with the skill itself.
They are often a better fit than agent-owned hooks because the workflow step, not the whole agent identity, is what owns the behavior.

## Good skill boundaries

A skill should usually:

- express one reusable procedure
- stay narrower than a whole app shell
- avoid becoming a dumping ground for unrelated prompt behavior
- expose a clean contract to callers

## Expected result

The runtime discovers the skill and can execute it as a reusable named workflow step.

## Next step

Validate the seam with `python3 -B -m examples.skills.file_backed_skill_demo`, `python3 -B -m examples.skills.inline_vs_fork_skill_demo`, or `python3 -B -m examples.skills.inline_skill_hook_demo`.

## See also

- `../concepts/tools-agents-skills.md`
- `../../examples/skills/workspace/.weavert/skills/release-summary/SKILL.md`
- `../deep-dives/weavert-definition-authoring-guide.md`
